"""Parse an annual report PDF into pages of text and table blocks.

Each page keeps its bank, year, PDF page number and section heading, so every
chunk built from it can be cited back to a page.

Choices worth knowing about:
- Page numbers are PDF page numbers (1-based), the page a PDF viewer jumps to.
  Printed page labels differ in some reports (Nordea is off by one).
- Tables are located with PyMuPDF's table finder, but their text is rebuilt row
  by row from word positions. The finder's own cell output merges columns on
  many report tables; the row rebuild keeps each label next to its figures.
- Navigation bars and footers that repeat on most pages are dropped.
"""

from __future__ import annotations

import collections
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Literal

import pymupdf

HEADER_ZONE = 0.12  # top share of the page where navigation bars live
FOOTER_ZONE = 0.93  # lines below this share of the height count as footer
BOILERPLATE_MIN_SHARE = 0.3  # a header/footer line on 30% of pages is boilerplate
MIN_HEADING_SIZE = 12.0
MIN_SECTION_SIZE = 18.0
NAV_MIN_STYLE_DISTANCE = 100  # how different the active navigation tab must look
FIGURE_RE = re.compile(r"^(DKK|EUR|SEK|NOK|USD)?\s*[-+]?[\d.,]+\s*(%|bn|m|million|billion)?\b", re.I)
NOT_TITLES = re.compile(r"^(contents|table of contents|annual report( \d{4})?)$", re.I)


@dataclass
class Block:
    kind: Literal["text", "table"]
    text: str


@dataclass
class Page:
    bank: str
    year: int
    page: int
    section: str
    heading: str
    blocks: list[Block] = field(default_factory=list)
    part: str = ""  # top-level part of the report, from the navigation bar

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Page:
        return cls(**{**d, "blocks": [Block(**b) for b in d["blocks"]]})


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip())


def _line_text(line: dict) -> str:
    return "".join(span["text"] for span in line["spans"]).strip()


def _in_margin(bbox: tuple[float, float, float, float], height: float) -> bool:
    return bbox[1] < HEADER_ZONE * height or bbox[1] > FOOTER_ZONE * height


def _find_boilerplate(doc: pymupdf.Document) -> set[str]:
    """Lines in the header or footer zone that repeat on many pages."""
    counts: collections.Counter[str] = collections.Counter()
    for page in doc:
        seen = set()
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = _norm(_line_text(line))
                if text and _in_margin(line["bbox"], page.rect.height):
                    seen.add(text)
        counts.update(seen)
    return {t for t, c in counts.items() if c >= BOILERPLATE_MIN_SHARE * doc.page_count}


def _toc_sections(doc: pymupdf.Document) -> list[tuple[int, str]]:
    """(start page, "Level 1 > Level 2") pairs from the PDF outline, if it has one."""
    path: list[str] = []
    out = []
    for level, title, page in doc.get_toc():
        # Nordea's outline names whole parts "Table of Contents Nordea Group" and has
        # bare "Table of Contents" entries. Strip that, and fall back to the parent.
        title = re.sub(r"^table of contents\s*", "", " ".join(title.split()), flags=re.I)
        path = path[: level - 1] + ([title] if title else [])
        # The top entry is usually the report title, which adds nothing.
        out.append((page, " > ".join(path[1:] if len(path) > 1 else path)))
    return out


def is_title(text: str) -> bool:
    """Whether large text reads like a heading, not a chart label or a figure callout."""
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


def _nav_part(page: pymupdf.Page, data: dict, boilerplate: set[str]) -> str:
    """The navigation tab that is styled differently from the others, if any.

    Danske Bank marks the current part of the report with white text, Nordea with
    bold. The tab whose colour or weight stands out most from the majority wins.
    """
    tabs = []
    for block in data["blocks"]:
        for line in block.get("lines", []):
            text = _line_text(line)
            in_header = line["bbox"][1] < HEADER_ZONE * page.rect.height
            # Tabs are short titles; this skips page numbers, running headers and
            # navigation bars set as one line of text (Jyske Bank).
            if in_header and _norm(text) in boilerplate and is_title(text) and len(text.split()) <= 6:
                span = max(line["spans"], key=lambda s: len(s["text"].strip()))
                tabs.append((text, span["color"], bool(span["flags"] & 16)))
    if len(tabs) < 3:
        return ""
    majority = collections.Counter((c, b) for _, c, b in tabs).most_common(1)[0][0]

    def distance(color: int, bold: bool) -> float:
        rgb = [(color >> s) & 255 for s in (16, 8, 0)]
        base = [(majority[0] >> s) & 255 for s in (16, 8, 0)]
        return sum((a - b) ** 2 for a, b in zip(rgb, base, strict=True)) ** 0.5 + 255 * (bold != majority[1])

    text, color, bold = max(tabs, key=lambda t: distance(t[1], t[2]))
    return text if distance(color, bold) >= NAV_MIN_STYLE_DISTANCE else ""


def _heading(spans: list[tuple[float, float, str]]) -> tuple[float, str]:
    """The top-most run of lines in the largest font: (size, text)."""
    if not spans:
        return 0.0, ""
    top = max(s for s, _, _ in spans)
    lines = sorted((y, t) for s, y, t in spans if s == top)
    out = [lines[0]]
    for y, t in lines[1:]:
        if y - out[-1][0] > 2 * top:  # a gap: the next heading, not a second line of this one
            break
        out.append((y, t))
    return top, " ".join(t for _, t in out)


def _inside(bbox: tuple[float, ...], rect: tuple[float, ...]) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _render_table(words: list[tuple], col_gap: float) -> str:
    """Rebuild a table as Markdown-style rows from word boxes.

    Words are grouped into rows by vertical position, then split into cells
    wherever the horizontal gap is wider than a normal space.
    """
    if not words:
        return ""
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    row_tol = 0.5 * median(w[3] - w[1] for w in words)
    rows: list[list[tuple]] = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        if rows and abs(yc - (rows[-1][0][1] + rows[-1][0][3]) / 2) <= row_tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        cells = [row[0][4]]
        for prev, w in zip(row, row[1:], strict=False):
            if w[0] - prev[2] > col_gap:
                cells.append(w[4])
            else:
                cells[-1] += " " + w[4]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line
        else:
            text = f"{text} {line}" if text else line
    return text


def iter_pages(
    path: Path, bank: str, year: int, start_page: int = 1, no_layout: frozenset[int] = frozenset()
) -> Iterator[Page]:
    """Yield parsed pages from start_page on.

    PyMuPDF 2.0 finds tables with a layout model, which is the only way it finds
    tables without ruling lines (most of Nordea's). On a few pages that model
    crashes the whole process. Pages listed in no_layout use line-based table
    detection only; the pipeline fills that list when a page crashes.

    Sections are set only on pages that start one. Run fill_sections over the
    full list to carry them forward.
    """
    doc = pymupdf.open(path)
    boilerplate = _find_boilerplate(doc)
    toc = _toc_sections(doc)

    for page in doc.pages(start_page - 1):
        pno = page.number + 1
        height = page.rect.height
        data = page.get_text("dict")

        # Body font size: the size covering the most characters on the page.
        size_chars: collections.Counter[float] = collections.Counter()
        for block in data["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    size_chars[round(span["size"], 1)] += len(span["text"].strip())
        body_size = size_chars.most_common(1)[0][0] if size_chars else 10.0

        found = page.find_tables(use_layout=pno not in no_layout)
        tables = [t for t in found.tables if t.row_count >= 2 and t.col_count >= 2]
        table_rects = [tuple(t.bbox) for t in tables]

        items: list[tuple[float, Block]] = []
        heading_spans: list[tuple[float, float, str]] = []  # (size, y, text)
        for block in data["blocks"]:
            lines = []
            for line in block.get("lines", []):
                text = _line_text(line)
                if not text or _norm(text) in boilerplate:
                    continue
                if _in_margin(line["bbox"], height) and re.fullmatch(r"\d{1,3}", text):
                    continue  # page number
                if any(_inside(line["bbox"], r) for r in table_rects):
                    continue
                size = max(round(s["size"], 1) for s in line["spans"])
                if size >= MIN_HEADING_SIZE and size >= 1.3 * body_size and is_title(text):
                    heading_spans.append((size, line["bbox"][1], text))
                lines.append(text)
            if lines:
                items.append((block["bbox"][1], Block("text", _join_lines(lines))))

        if tables:
            words = page.get_text("words")
            col_gap = 0.8 * body_size
            for rect in table_rects:
                inside = [w for w in words if _inside(w[:4], rect)]
                text = _render_table(inside, col_gap)
                if text:
                    items.append((rect[1], Block("table", text)))

        # Keep PyMuPDF's reading order for text, and slot each table in before
        # the first text block that starts below it.
        texts = [it for it in items if it[1].kind == "text"]
        tabs = sorted((it for it in items if it[1].kind == "table"), key=lambda it: it[0])
        ordered: list[Block] = []
        for y, blk in texts:
            while tabs and tabs[0][0] <= y:
                ordered.append(tabs.pop(0)[1])
            ordered.append(blk)
        ordered.extend(blk for _, blk in tabs)

        size, heading = _heading(heading_spans)
        section, part = "", ""
        if toc:
            section = next((name for start, name in reversed(toc) if start <= pno), "")
        else:
            part = _nav_part(page, data, boilerplate)
            if size >= MIN_SECTION_SIZE:
                section = heading

        yield Page(
            bank=bank, year=year, page=pno, section=section, heading=heading, blocks=ordered, part=part
        )


def fill_sections(pages: list[Page]) -> list[Page]:
    """Carry each section forward to the pages that follow it, and prefix the part.

    A section ends at the next section or when the report moves to another part.
    Reports with a PDF outline already have a full section path on every page.
    """
    section, part = "", ""
    for page in pages:
        if page.part != part:
            section, part = "", page.part
        section = page.section or section
        page.section = " > ".join(s for s in (part, section) if s)
    return pages


def parse_pdf(path: Path, bank: str, year: int) -> list[Page]:
    return fill_sections(list(iter_pages(path, bank, year)))
