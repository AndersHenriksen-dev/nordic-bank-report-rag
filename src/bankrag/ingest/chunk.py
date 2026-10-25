"""Turn parsed pages into chunks for retrieval.

Strategy "structure" (the default):
- Chunks never cross a page, so every chunk cites exactly one page.
- Paragraphs are packed together up to about TARGET_TOKENS. The last paragraph
  of a chunk is repeated at the start of the next one as overlap.
- A table is never split unless it is longer than MAX_TABLE_TOKENS. Then it is
  cut between rows and the first two rows (the column headers) are repeated.
- Each chunk starts with a context line (bank, report, page, section), which
  helps both keyword search and the answer model know where the text is from.

Strategy "fixed" is the baseline to compare against in the evals: windows of a
fixed size over the page text, ignoring paragraphs and tables.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from bankrag.config import bank_name
from bankrag.ingest.pdf import Block, Page

TARGET_TOKENS = 500
MAX_TOKENS = 800
MAX_TABLE_TOKENS = 1200
OVERLAP_MAX_TOKENS = 150
FIXED_WINDOW_TOKENS = 500
FIXED_OVERLAP_TOKENS = 100


def estimate_tokens(text: str) -> int:
    """Rough token count. Report text with many figures is about 3.5 characters per token."""
    return max(1, round(len(text) / 3.5))


@dataclass
class Chunk:
    id: str
    bank: str
    year: int
    page: int
    section: str
    heading: str
    text: str  # includes the context line
    body: str  # the text without the context line, as cited back to the user
    has_table: bool

    def to_dict(self) -> dict:
        return asdict(self)


def context_line(page: Page) -> str:
    where = page.heading or page.section
    if page.section and page.heading and page.heading not in page.section:
        where = f"{page.section} > {page.heading}"
    parts = [bank_name(page.bank), f"Annual Report {page.year}", f"page {page.page}"]
    if where:
        parts.append(where)
    return "[" + " | ".join(parts) + "]"


def _split_table(text: str) -> list[str]:
    rows = text.split("\n")
    header, body = rows[:2], rows[2:]
    parts, current = [], list(header)
    for row in body:
        if estimate_tokens("\n".join(current + [row])) > MAX_TABLE_TOKENS and len(current) > len(header):
            parts.append("\n".join(current))
            current = list(header)
        current.append(row)
    parts.append("\n".join(current))
    return parts


def _units(blocks: Iterable[Block]) -> list[Block]:
    """Blocks small enough to pack: big tables are split between rows."""
    out = []
    for b in blocks:
        if b.kind == "table" and estimate_tokens(b.text) > MAX_TABLE_TOKENS:
            out.extend(Block("table", part) for part in _split_table(b.text))
        else:
            out.append(b)
    return out


def _make_chunk(page: Page, n: int, parts: list[Block]) -> Chunk:
    body = "\n\n".join(b.text for b in parts)
    return Chunk(
        id=f"{page.bank}-{page.year}-p{page.page:03d}-c{n:02d}",
        bank=page.bank,
        year=page.year,
        page=page.page,
        section=page.section,
        heading=page.heading,
        text=f"{context_line(page)}\n{body}",
        body=body,
        has_table=any(b.kind == "table" for b in parts),
    )


def chunk_page_structure(page: Page) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: list[Block] = []
    size = 0
    only_overlap = False  # current holds nothing but text already in the previous chunk
    for unit in _units(page.blocks):
        unit_size = estimate_tokens(unit.text)
        if current and not only_overlap and (size + unit_size > MAX_TOKENS or size >= TARGET_TOKENS):
            chunks.append(_make_chunk(page, len(chunks), current))
            last = current[-1]
            # Carry the last paragraph over as overlap, but never a table.
            if last.kind == "text" and estimate_tokens(last.text) <= OVERLAP_MAX_TOKENS:
                current, size, only_overlap = [last], estimate_tokens(last.text), True
            else:
                current, size = [], 0
        current.append(unit)
        size += unit_size
        only_overlap = False
    if current and not only_overlap:
        chunks.append(_make_chunk(page, len(chunks), current))
    return chunks


def chunk_page_fixed(page: Page) -> list[Chunk]:
    text = "\n\n".join(b.text for b in page.blocks)
    if not text.strip():
        return []
    window = int(FIXED_WINDOW_TOKENS * 3.5)
    step = int((FIXED_WINDOW_TOKENS - FIXED_OVERLAP_TOKENS) * 3.5)
    chunks = []
    for start in range(0, max(1, len(text) - (window - step)), step):
        piece = text[start : start + window]
        chunks.append(_make_chunk(page, len(chunks), [Block("text", piece)]))
    return chunks


STRATEGIES = {
    "structure": chunk_page_structure,
    "fixed": chunk_page_fixed,
}


def chunk_pages(pages: Iterable[Page], strategy: str = "structure") -> list[Chunk]:
    fn = STRATEGIES[strategy]
    return [c for page in pages for c in fn(page) if c.body.strip()]
