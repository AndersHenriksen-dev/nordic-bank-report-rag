"""Find cited passages on a PDF page and render the page with them highlighted.

Cited passages are the parser's text, not the PDF's: tables were rebuilt as rows of cells and lines were joined. So a
passage is not searched as one string. Prose is searched in overlapping windows of a few words, so one odd character
loses one window, not the sentence. A table row is found by its label, and only numbers on the label's line are
highlighted, because a figure like "17.3" can appear several times on a page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from bankrag.figures import figures_in

WINDOW_WORDS = 8
WINDOW_STEP = 4
MIN_LABEL_LETTERS = 3
ROW_TOLERANCE = 2.0  # points a cell may sit above or below its label and still count as the same row
ZOOM = 1.6
CLOSE_UP_MARGIN = 40.0  # points of context around the highlighted area
CLOSE_UP_MIN_WIDTH = 360.0  # points; narrower close-ups lose the surrounding text

# PyMuPDF "words" mode: x0, y0, x1, y1, text, block number, line number, word number.
Word = tuple[float, float, float, float, str, int, int, int]


def _prose_windows(paragraph: str) -> list[str]:
    """Split a paragraph into overlapping windows of words to search for."""
    words = paragraph.split()
    if len(words) <= WINDOW_WORDS:
        return [" ".join(words)] if words else []
    starts = range(0, len(words) - WINDOW_WORDS + WINDOW_STEP, WINDOW_STEP)
    return [" ".join(words[start : start + WINDOW_WORDS]) for start in starts]


def _row_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|") if cell.strip()]


def _same_row(rect: pymupdf.Rect, label: pymupdf.Rect) -> bool:
    center = (rect.y0 + rect.y1) / 2
    return label.y0 - ROW_TOLERANCE <= center <= label.y1 + ROW_TOLERANCE


def _words_between(words: list[Word], label: pymupdf.Rect, first_cell: pymupdf.Rect) -> bool:
    """Tell whether any word sits on the label's line between the label and the row's first cell.

    In a table the space after a label is empty; in prose ("Income tax expense amounted to EUR -1,476m") it is not.
    """
    return any(
        label.x1 + 1 < (word[0] + word[2]) / 2 < first_cell.x0 - 1 and _same_row(pymupdf.Rect(word[:4]), label)
        for word in words
    )


def _table_row_rects(page: pymupdf.Page, words: list[Word], cells: list[str]) -> list[pymupdf.Rect]:
    """Find a table row by its label cell, then the row's other cells on the same line.

    A label match counts only if at least half of the row's other cells are found on its line with nothing written in
    between, so a common label such as "Total", or the same words in a sentence, does not light up. Rows without
    figures (a group heading inside a table, or a header row such as "EURm | 2025 | 2024") are skipped: they repeat
    on many tables and carry no claim.
    """
    label = next((cell for cell in cells if sum(c.isalpha() for c in cell) >= MIN_LABEL_LETTERS), None)
    others = [cell for cell in cells if cell != label]
    if label is None or not figures_in(" ".join(others)):
        return []
    cell_rects = {cell: page.search_for(cell) for cell in set(others)}
    rects: list[pymupdf.Rect] = []
    for label_rect in page.search_for(label):
        on_row = {
            cell: [rect for rect in cell_rects[cell] if _same_row(rect, label_rect) and rect.x0 > label_rect.x1]
            for cell in set(others)
        }
        found = [rect for matches in on_row.values() for rect in matches]
        enough = sum(1 for cell in others if on_row[cell]) * 2 >= len(others)
        if enough and not (found and _words_between(words, label_rect, min(found, key=lambda rect: rect.x0))):
            rects += [label_rect, *found]
    return rects


def _near(rect: pymupdf.Rect, other: pymupdf.Rect) -> bool:
    """Tell whether two matches sit within a few lines of each other in the same column."""
    same_column = other.x0 < rect.x1 and rect.x0 < other.x1
    return same_column and abs(rect.y0 - other.y0) <= 3 * max(rect.height, other.height)


def _paragraph_rects(page: pymupdf.Page, paragraph: str) -> list[pymupdf.Rect]:
    """Find a paragraph by its windows, keeping only matches that a neighbouring window confirms.

    A short phrase such as "At the end of December 2025" can occur several times on a page; the true occurrence is
    the one next to the matches of the windows around it.
    """
    matches = [page.search_for(window) for window in _prose_windows(paragraph)]
    if len(matches) == 1:
        return matches[0]
    return [
        rect
        for index, rects in enumerate(matches)
        for rect in rects
        if any(
            _near(rect, other) for other_index, others in enumerate(matches) if other_index != index for other in others
        )
    ]


def _is_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def focus_passage(passage: str, focus: set[float]) -> str:
    """Cut each table in a passage to the rows that share a figure with the answer.

    Claude cites a whole table block, but an answer usually uses one or two of its rows. Header rows, which hold no
    figures (only years and units), are kept for context. A table that shares no figure with the answer is kept whole.
    """
    blocks = []
    for block in passage.split("\n\n"):
        lines = block.split("\n")
        rows = [line for line in lines if _is_row(line)]
        used = [row for row in rows if figures_in(row) & focus]
        headers = [row for row in rows if not figures_in(row)]
        keep = set(used + headers) if used else set(rows)
        blocks.append("\n".join(line for line in lines if not _is_row(line) or line in keep))
    return "\n\n".join(blocks)


def find_passage_rects(page: pymupdf.Page, passage: str) -> list[pymupdf.Rect]:
    """Return the areas of a page that hold a cited passage (paragraphs and table rows)."""
    words: list[Word] = page.get_text("words")
    rects: list[pymupdf.Rect] = []
    for block in passage.split("\n\n"):
        for line in block.split("\n"):
            if _is_row(line):
                rects += _table_row_rects(page, words, _row_cells(line))
            else:
                rects += _paragraph_rects(page, line)
    return rects


@dataclass(frozen=True)
class HighlightedPage:
    """A cited page as PNG images: a close-up of the highlighted area, if one was found, and the whole page."""

    close_up: bytes | None
    whole_page: bytes


def _close_up_area(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> pymupdf.Rect:
    """Return the highlighted area with some margin, at least CLOSE_UP_MIN_WIDTH wide, within the page."""
    x0 = min(rect.x0 for rect in rects) - CLOSE_UP_MARGIN
    y0 = min(rect.y0 for rect in rects) - CLOSE_UP_MARGIN
    x1 = max(rect.x1 for rect in rects) + CLOSE_UP_MARGIN
    y1 = max(rect.y1 for rect in rects) + CLOSE_UP_MARGIN
    grow = max(0.0, (CLOSE_UP_MIN_WIDTH - (x1 - x0)) / 2)
    bounds = page.rect
    return pymupdf.Rect(max(bounds.x0, x0 - grow), max(bounds.y0, y0), min(bounds.x1, x1 + grow), min(bounds.y1, y1))


def render_highlighted_page(pdf: Path, page_number: int, passages: list[str], focus: set[float]) -> HighlightedPage:
    """Render a PDF page with the cited passages highlighted. The PDF on disk is not changed.

    Report pages are often wide spreads where a highlighted paragraph is small, so a close-up of the highlighted area
    is rendered as well. Pages where the passages cannot be located get no close-up.

    Args:
        pdf: The report.
        page_number: 1-based PDF page number.
        passages: The passages Claude cited on this page.
        focus: Figures from the answer, so a cited table highlights only the rows the answer uses.
    """
    with pymupdf.open(pdf) as doc:
        page = doc[page_number - 1]
        rects = [rect for passage in passages for rect in find_passage_rects(page, focus_passage(passage, focus))]
        if rects:
            page.add_highlight_annot(rects)
        matrix = pymupdf.Matrix(ZOOM, ZOOM)
        whole_page: bytes = page.get_pixmap(matrix=matrix).tobytes("png")
        close_up: bytes | None = None
        if rects:
            close_up = page.get_pixmap(matrix=matrix, clip=_close_up_area(page, rects)).tobytes("png")
    return HighlightedPage(close_up=close_up, whole_page=whole_page)
