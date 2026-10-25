"""Turn parsed pages into chunks for retrieval.

Strategy "structure" (the default): chunks never cross a page, so every chunk cites exactly one page. Paragraphs are
packed up to about TARGET_TOKENS, and the last paragraph of a chunk is repeated at the start of the next as overlap. A
table is never split unless it is longer than MAX_TABLE_TOKENS; then it is cut between rows with the header rows
repeated. Each chunk starts with a context line (bank, report, page, section) that helps keyword search.

Strategy "fixed" is the baseline the evals compare against: fixed-size windows over the page text that ignore
paragraphs and tables.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal

from bankrag.config import bank_name
from bankrag.models import Block, Chunk, Page

ChunkStrategy = Literal["structure", "fixed"]

TARGET_TOKENS = 500
MAX_TOKENS = 800
MAX_TABLE_TOKENS = 1200
OVERLAP_MAX_TOKENS = 150
FIXED_WINDOW_TOKENS = 500
FIXED_OVERLAP_TOKENS = 100
CHARS_PER_TOKEN = 3.5  # report text with many figures


def estimate_tokens(text: str) -> int:
    """Estimate the token count of report text from its length."""
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def _context_line(page: Page) -> str:
    where = page.heading or page.section
    if page.section and page.heading and page.heading not in page.section:
        where = f"{page.section} > {page.heading}"
    parts = [bank_name(page.bank), f"Annual Report {page.year}", f"page {page.page}"]
    if where:
        parts.append(where)
    return "[" + " | ".join(parts) + "]"


def _split_table(text: str) -> list[str]:
    """Cut a long table between rows, repeating the first two rows (the column headers) in each part."""
    rows = text.split("\n")
    header, body = rows[:2], rows[2:]
    parts: list[str] = []
    current = list(header)
    for row in body:
        if estimate_tokens("\n".join([*current, row])) > MAX_TABLE_TOKENS and len(current) > len(header):
            parts.append("\n".join(current))
            current = list(header)
        current.append(row)
    parts.append("\n".join(current))
    return parts


def _packable_units(blocks: Iterable[Block]) -> list[Block]:
    """Return the blocks ready for packing, with tables over MAX_TABLE_TOKENS split between rows."""
    units: list[Block] = []
    for block in blocks:
        if block.kind == "table" and estimate_tokens(block.text) > MAX_TABLE_TOKENS:
            units.extend(Block(kind="table", text=part) for part in _split_table(block.text))
        else:
            units.append(block)
    return units


def _make_chunk(page: Page, number: int, parts: list[Block]) -> Chunk:
    body = "\n\n".join(block.text for block in parts)
    return Chunk(
        id=f"{page.bank}-{page.year}-p{page.page:03d}-c{number:02d}",
        bank=page.bank,
        year=page.year,
        page=page.page,
        section=page.section,
        heading=page.heading,
        text=f"{_context_line(page)}\n{body}",
        body=body,
        has_table=any(block.kind == "table" for block in parts),
    )


def chunk_page_structure(page: Page) -> list[Chunk]:
    """Pack a page's paragraphs and tables into chunks of about TARGET_TOKENS, without splitting tables."""
    chunks: list[Chunk] = []
    current: list[Block] = []
    size = 0
    only_overlap = False  # current holds nothing but text already in the previous chunk
    for unit in _packable_units(page.blocks):
        unit_size = estimate_tokens(unit.text)
        if current and not only_overlap and (size + unit_size > MAX_TOKENS or size >= TARGET_TOKENS):
            chunks.append(_make_chunk(page, len(chunks), current))
            last = current[-1]
            # Repeating a table as overlap would double the largest blocks on the page.
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
    """Cut a page's text into fixed windows of FIXED_WINDOW_TOKENS with FIXED_OVERLAP_TOKENS of overlap."""
    text = "\n\n".join(block.text for block in page.blocks)
    if not text.strip():
        return []
    window = int(FIXED_WINDOW_TOKENS * CHARS_PER_TOKEN)
    step = int((FIXED_WINDOW_TOKENS - FIXED_OVERLAP_TOKENS) * CHARS_PER_TOKEN)
    chunks: list[Chunk] = []
    for start in range(0, max(1, len(text) - (window - step)), step):
        piece = text[start : start + window]
        chunks.append(_make_chunk(page, len(chunks), [Block(kind="text", text=piece)]))
    return chunks


STRATEGIES: dict[ChunkStrategy, Callable[[Page], list[Chunk]]] = {
    "structure": chunk_page_structure,
    "fixed": chunk_page_fixed,
}


def chunk_pages(pages: Iterable[Page], strategy: ChunkStrategy) -> list[Chunk]:
    """Chunk every page with the given strategy, dropping chunks with no text."""
    chunk_page = STRATEGIES[strategy]
    return [chunk for page in pages for chunk in chunk_page(page) if chunk.body.strip()]
