"""Tests for structure-aware chunking: context lines, whole tables and overlap."""

from __future__ import annotations

import itertools

from bankrag.ingest.chunk import MAX_TABLE_TOKENS, chunk_page_structure, estimate_tokens
from bankrag.models import Block, Page


def page(blocks: list[Block]) -> Page:
    return Page(bank="danske", year=2025, page=10, section="Financial review", heading="Income", blocks=blocks)


def text(content: str) -> Block:
    return Block(kind="text", text=content)


def table(content: str) -> Block:
    return Block(kind="table", text=content)


def test_chunks_carry_context_line_and_page() -> None:
    chunks = chunk_page_structure(page([text("Net profit was DKK 23,037 million.")]))
    assert len(chunks) == 1
    assert chunks[0].text.startswith("[Danske Bank | Annual Report 2025 | page 10 | Financial review > Income]")
    assert chunks[0].page == 10


def test_table_is_not_split_when_it_fits() -> None:
    rows = "\n".join(f"| Row {i} | {i},000 | {i},100 |" for i in range(60))
    assert estimate_tokens(rows) < MAX_TABLE_TOKENS
    chunks = chunk_page_structure(page([text("Intro. " * 300), table(rows)]))
    assert sum(rows in chunk.body for chunk in chunks) == 1


def test_large_table_is_split_between_rows_with_headers_repeated() -> None:
    rows = ["| (DKK millions) | 2025 | 2024 |", "| --- | --- | --- |"]
    rows += [f"| Line item number {i} | {i},000 | {i},100 |" for i in range(400)]
    chunks = chunk_page_structure(page([table("\n".join(rows))]))
    assert len(chunks) > 1
    assert all(chunk.body.startswith("| (DKK millions) | 2025 | 2024 |") for chunk in chunks)


def test_overlap_paragraph_is_not_emitted_alone() -> None:
    chunks = chunk_page_structure(page([text(f"Paragraph {i}. " + "word " * 300) for i in range(3)]))
    assert chunks[-1].body.split("\n\n")[-1].startswith("Paragraph 2")
    for previous, current in itertools.pairwise(chunks):
        assert current.body != previous.body.split("\n\n")[-1]
