"""Parse an annual report PDF into pages of text and table blocks.

Each page keeps its bank, year, PDF page number and section, so every chunk built from it can be cited back to a
page. Tables are located with PyMuPDF's table finder, but their text is rebuilt row by row from word positions: the
finder's own cell output merges columns on many report tables. Navigation bars and footers that repeat on most pages
are dropped.
"""

from __future__ import annotations

import collections
import itertools
import math
import re
from collections.abc import Iterator
from pathlib import Path
from statistics import median
from typing import Any

import pymupdf

from bankrag.config import Bank
from bankrag.models import Block, Page

HEADER_ZONE = 0.12  # top share of the page where navigation bars live
FOOTER_ZONE = 0.93  # lines below this share of the height count as footer
BOILERPLATE_MIN_SHARE = 0.3  # a header or footer line on 30% of pages is boilerplate
MIN_HEADING_SIZE = 12.0
MIN_SECTION_SIZE = 18.0
NAV_MIN_STYLE_DISTANCE = 100  # how different the active navigation tab must look
BOLD_FLAG = 16
FIGURE_RE = re.compile(r"^(DKK|EUR|SEK|NOK|USD)?\s*[-+]?[\d.,]+\s*(%|bn|m|million|billion)?\b", re.IGNORECASE)
NOT_TITLES = re.compile(r"^(contents|table of contents|annual report( \d{4})?)$", re.IGNORECASE)

# PyMuPDF returns page content as untyped nested dicts ("dict" mode), so Any is the narrowest honest type for them.
PageDict = dict[str, Any]
LineDict = dict[str, Any]
Rect = tuple[float, float, float, float]
# PyMuPDF "words" mode: x0, y0, x1, y1, text, block number, line number, word number.
Word = tuple[float, float, float, float, str, int, int, int]
HeadingLine = tuple[float, float, str]  # font size, top y, text
NavTab = tuple[str, int, bool]  # text, colour as 0xRRGGBB, bold
TocEntry = tuple[int, str]  # start page, "Part > Section"


def is_title(text: str) -> bool:
    """Tell whether large text reads like a heading rather than a chart label or a figure callout."""
    text = text.strip()
    letters = sum(c.isalpha() for c in text)
    visible = sum(not c.isspace() for c in text)
    return (
        letters >= 4
        and letters >= 0.6 * visible
        and (text[0].isupper() or text[0].isdigit())
        and len(text.split()) <= 12
        and not FIGURE_RE.match(text)
        and not NOT_TITLES.match(text)
    )


def _mask_digits(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip())


def _line_text(line: LineDict) -> str:
    return "".join(span["text"] for span in line["spans"]).strip()


def _in_margin(bbox: Rect, height: float) -> bool:
    return bbox[1] < HEADER_ZONE * height or bbox[1] > FOOTER_ZONE * height


def _inside(bbox: Rect, rect: Rect) -> bool:
    center_x, center_y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] <= center_x <= rect[2] and rect[1] <= center_y <= rect[3]


def _find_boilerplate(doc: pymupdf.Document) -> set[str]:
    """Find header and footer lines that repeat on many pages, with digits masked so page numbers match."""
    counts: collections.Counter[str] = collections.Counter()
    for page in doc.pages():
        seen = set()
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = _mask_digits(_line_text(line))
                if text and _in_margin(line["bbox"], page.rect.height):
                    seen.add(text)
        counts.update(seen)
    return {text for text, count in counts.items() if count >= BOILERPLATE_MIN_SHARE * doc.page_count}


def _toc_sections(doc: pymupdf.Document) -> list[TocEntry]:
    """Read section paths from the PDF outline, if the report has one."""
    path: list[str] = []
    entries = []
    for level, raw_title, page in doc.get_toc():
        # Nordea's outline names whole parts "Table of Contents Nordea Group" and has bare "Table of Contents"
        # entries. Strip that, and fall back to the parent.
        title = re.sub(r"^table of contents\s*", "", " ".join(raw_title.split()), flags=re.IGNORECASE)
        path = path[: level - 1] + ([title] if title else [])
        # The top entry is usually the report title, which adds nothing.
        entries.append((page, " > ".join(path[1:] if len(path) > 1 else path)))
    return entries


def _body_font_size(page_dict: PageDict) -> float:
    """Return the font size that covers the most characters on the page."""
    chars_by_size: collections.Counter[float] = collections.Counter()
    for block in page_dict["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars_by_size[round(span["size"], 1)] += len(span["text"].strip())
    return chars_by_size.most_common(1)[0][0] if chars_by_size else 10.0


def _find_table_rects(page: pymupdf.Page, use_layout: bool) -> list[Rect]:
    found = page.find_tables(use_layout=use_layout)
    return [tuple(table.bbox) for table in found.tables if table.row_count >= 2 and table.col_count >= 2]


def _join_lines(lines: list[str]) -> str:
    """Join the lines of one text block, mending words hyphenated across a line break."""
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line
            continue
        text = f"{text} {line}" if text else line
    return text


def _text_blocks(
    page_dict: PageDict,
    height: float,
    boilerplate: set[str],
    table_rects: list[Rect],
    body_size: float,
) -> tuple[list[tuple[float, Block]], list[HeadingLine]]:
    """Collect the page's text blocks outside tables, and the lines large enough to be headings.

    Returns:
        Text blocks with their top y position, and heading candidates as (font size, top y, text).
    """
    blocks: list[tuple[float, Block]] = []
    heading_lines: list[HeadingLine] = []
    for block in page_dict["blocks"]:
        lines = []
        for line in block.get("lines", []):
            text = _line_text(line)
            if not text or _mask_digits(text) in boilerplate:
                continue
            is_page_number = _in_margin(line["bbox"], height) and re.fullmatch(r"\d{1,3}", text)
            if is_page_number or any(_inside(line["bbox"], rect) for rect in table_rects):
                continue
            size = max(round(span["size"], 1) for span in line["spans"])
            if size >= MIN_HEADING_SIZE and size >= 1.3 * body_size and is_title(text):
                heading_lines.append((size, line["bbox"][1], text))
            lines.append(text)
        if lines:
            blocks.append((block["bbox"][1], Block(kind="text", text=_join_lines(lines))))
    return blocks, heading_lines


def _group_rows(words: list[Word]) -> list[list[Word]]:
    """Group words into table rows by vertical position, each row sorted left to right."""
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    row_tolerance = 0.5 * median(w[3] - w[1] for w in words)
    rows: list[list[Word]] = []
    for word in words:
        center_y = (word[1] + word[3]) / 2
        if rows and abs(center_y - (rows[-1][0][1] + rows[-1][0][3]) / 2) <= row_tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda w: w[0]) for row in rows]


def _row_cells(row: list[Word], col_gap: float) -> list[str]:
    """Split a row into cells wherever the gap between two words is wider than a normal space."""
    cells = [row[0][4]]
    for previous, word in itertools.pairwise(row):
        if word[0] - previous[2] > col_gap:
            cells.append(word[4])
        else:
            cells[-1] += " " + word[4]
    return cells


def _render_table(words: list[Word], col_gap: float) -> str:
    """Rebuild a table as rows of cells separated by "|", from the word boxes inside it."""
    if not words:
        return ""
    return "\n".join("| " + " | ".join(_row_cells(row, col_gap)) + " |" for row in _group_rows(words))


def _table_blocks(page: pymupdf.Page, table_rects: list[Rect], body_size: float) -> list[tuple[float, Block]]:
    if not table_rects:
        return []
    words: list[Word] = page.get_text("words")
    blocks = []
    for rect in table_rects:
        text = _render_table([w for w in words if _inside(w[:4], rect)], col_gap=0.8 * body_size)
        if text:
            blocks.append((rect[1], Block(kind="table", text=text)))
    return blocks


def _in_reading_order(texts: list[tuple[float, Block]], tables: list[tuple[float, Block]]) -> list[Block]:
    """Keep PyMuPDF's reading order for text and put each table before the first text block below it.

    Text order comes from PyMuPDF rather than from y positions, because reports set text in columns.
    """
    pending = sorted(tables, key=lambda item: item[0])
    ordered: list[Block] = []
    for top, block in texts:
        while pending and pending[0][0] <= top:
            ordered.append(pending.pop(0)[1])
        ordered.append(block)
    ordered.extend(block for _, block in pending)
    return ordered


def _heading(heading_lines: list[HeadingLine]) -> tuple[float, str]:
    """Return the top-most run of lines in the largest font, as (font size, text)."""
    if not heading_lines:
        return 0.0, ""
    top_size = max(size for size, _, _ in heading_lines)
    lines = sorted((y, text) for size, y, text in heading_lines if size == top_size)
    run = [lines[0]]
    for y, text in lines[1:]:
        if y - run[-1][0] > 2 * top_size:  # a gap: the next heading, not a second line of this one
            break
        run.append((y, text))
    return top_size, " ".join(text for _, text in run)


def _style_distance(tab: NavTab, majority: tuple[int, bool]) -> float:
    rgb = [(tab[1] >> shift) & 255 for shift in (16, 8, 0)]
    base = [(majority[0] >> shift) & 255 for shift in (16, 8, 0)]
    return math.dist(rgb, base) + 255 * (tab[2] != majority[1])


def _nav_part(page_dict: PageDict, height: float, boilerplate: set[str]) -> str:
    """Return the navigation tab styled differently from the others, which names the current part of the report.

    Danske Bank marks the current part with white text and Nordea with bold. The tab whose colour or weight stands
    out most from the majority wins.
    """
    tabs: list[NavTab] = []
    for block in page_dict["blocks"]:
        for line in block.get("lines", []):
            text = _line_text(line)
            in_header = line["bbox"][1] < HEADER_ZONE * height
            # Tabs are short titles. This skips page numbers, running headers and navigation bars set as a single
            # line of text (Jyske Bank's on some pages).
            if in_header and _mask_digits(text) in boilerplate and is_title(text) and len(text.split()) <= 6:
                span = max(line["spans"], key=lambda s: len(s["text"].strip()))
                tabs.append((text, span["color"], bool(span["flags"] & BOLD_FLAG)))
    if len(tabs) < 3:
        return ""
    majority = collections.Counter((colour, bold) for _, colour, bold in tabs).most_common(1)[0][0]
    standout = max(tabs, key=lambda tab: _style_distance(tab, majority))
    return standout[0] if _style_distance(standout, majority) >= NAV_MIN_STYLE_DISTANCE else ""


def _parse_page(
    page: pymupdf.Page,
    bank: Bank,
    year: int,
    boilerplate: set[str],
    toc: list[TocEntry],
    use_layout: bool,
) -> Page:
    page_number = page.number + 1
    page_dict: PageDict = page.get_text("dict")
    body_size = _body_font_size(page_dict)
    table_rects = _find_table_rects(page, use_layout)
    texts, heading_lines = _text_blocks(page_dict, page.rect.height, boilerplate, table_rects, body_size)
    tables = _table_blocks(page, table_rects, body_size)
    size, heading = _heading(heading_lines)

    section, part = "", ""
    if toc:
        section = next((name for start, name in reversed(toc) if start <= page_number), "")
    else:
        part = _nav_part(page_dict, page.rect.height, boilerplate)
        if size >= MIN_SECTION_SIZE:
            section = heading

    return Page(
        bank=bank,
        year=year,
        page=page_number,
        section=section,
        heading=heading,
        blocks=_in_reading_order(texts, tables),
        part=part,
    )


def iter_pages(
    path: Path,
    bank: Bank,
    year: int,
    start_page: int = 1,
    no_layout: frozenset[int] = frozenset(),
) -> Iterator[Page]:
    """Yield parsed pages from `start_page` on.

    PyMuPDF 2.0 finds tables with a layout model, the only way it finds tables without ruling lines (most of
    Nordea's). On a few pages that model crashes the whole process, so the pipeline runs this in a child process
    and restarts it with the crashing page in `no_layout`, which uses line-based table detection only.

    Sections are set only on pages that start one. Run `fill_sections` over the full list to carry them forward.
    """
    doc = pymupdf.open(path)
    boilerplate = _find_boilerplate(doc)
    toc = _toc_sections(doc)
    for page in doc.pages(start_page - 1):
        yield _parse_page(page, bank, year, boilerplate, toc, use_layout=page.number + 1 not in no_layout)


def fill_sections(pages: list[Page]) -> list[Page]:
    """Carry each section forward to the pages that follow it, and prefix the report part.

    A section ends at the next section or when the report moves to another part. Reports with a PDF outline already
    have a full section path on every page.
    """
    section, part = "", ""
    for page in pages:
        if page.part != part:
            section, part = "", page.part
        section = page.section or section
        page.section = " > ".join(s for s in (part, section) if s)
    return pages
