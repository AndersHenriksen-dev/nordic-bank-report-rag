from bankrag.ingest.chunk import MAX_TABLE_TOKENS, chunk_page_structure, estimate_tokens
from bankrag.ingest.pdf import Block, Page


def page(blocks: list[Block]) -> Page:
    return Page(
        bank="danske", year=2025, page=10, section="Financial review", heading="Income", blocks=blocks
    )


def test_chunks_carry_context_line_and_page():
    chunks = chunk_page_structure(page([Block("text", "Net profit was DKK 23,037 million.")]))
    assert len(chunks) == 1
    assert chunks[0].text.startswith(
        "[Danske Bank | Annual Report 2025 | page 10 | Financial review > Income]"
    )
    assert chunks[0].page == 10


def test_table_is_not_split_when_it_fits():
    table = "\n".join(f"| Row {i} | {i},000 | {i},100 |" for i in range(60))
    assert estimate_tokens(table) < MAX_TABLE_TOKENS
    chunks = chunk_page_structure(page([Block("text", "Intro. " * 300), Block("table", table)]))
    assert sum(table in c.body for c in chunks) == 1


def test_large_table_is_split_between_rows_with_headers_repeated():
    rows = ["| (DKK millions) | 2025 | 2024 |", "| --- | --- | --- |"]
    rows += [f"| Line item number {i} | {i},000 | {i},100 |" for i in range(400)]
    chunks = chunk_page_structure(page([Block("table", "\n".join(rows))]))
    assert len(chunks) > 1
    assert all(c.body.startswith("| (DKK millions) | 2025 | 2024 |") for c in chunks)


def test_overlap_paragraph_is_not_emitted_alone():
    paragraphs = [Block("text", f"Paragraph {i}. " + "word " * 300) for i in range(3)]
    chunks = chunk_page_structure(page(paragraphs))
    assert chunks
    assert all(len(c.body.split("\n\n")) >= 1 for c in chunks)
    assert chunks[-1].body.split("\n\n")[-1].startswith("Paragraph 2")
