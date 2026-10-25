"""Tests for the PDF parser's pure helpers: heading detection, table rows and section carry-forward."""

from __future__ import annotations

import pytest

from bankrag.ingest.pdf import Word, _render_table, fill_sections, is_title
from bankrag.models import Page


@pytest.mark.parametrize("text", ["Financial review", "Capital and liquidity management", "G11. Loan impairment"])
def test_is_title_accepts_headings(text: str) -> None:
    assert is_title(text)


@pytest.mark.parametrize(
    "text",
    ["DKK 6,307 million", "'24 …", "↘ 65%", "E", "statements", "Contents", "Annual Report 2024"],
)
def test_is_title_rejects_chart_labels_figures_and_fragments(text: str) -> None:
    assert not is_title(text)


def word(x0: float, y0: float, x1: float, text: str) -> Word:
    return (x0, y0, x1, y0 + 10, text, 0, 0, 0)


def test_render_table_keeps_labels_next_to_their_figures() -> None:
    words = [
        word(0, 0, 40, "Net"),
        word(45, 0, 80, "profit"),
        word(200, 0, 240, "23,037"),
        word(300, 0, 340, "23,629"),
        word(0, 20, 40, "Tax"),
        word(200, 20, 240, "7,662"),
        word(300, 20, 340, "7,583"),
    ]
    assert _render_table(words, col_gap=8) == "| Net profit | 23,037 | 23,629 |\n| Tax | 7,662 | 7,583 |"


def test_fill_sections_carries_forward_and_resets_on_a_new_part() -> None:
    pages = [
        Page(bank="danske", year=2025, page=1, section="Financial review", heading="", part="Management's report"),
        Page(bank="danske", year=2025, page=2, section="", heading="", part="Management's report"),
        Page(bank="danske", year=2025, page=3, section="", heading="", part="Financial statements"),
    ]
    assert [page.section for page in fill_sections(pages)] == [
        "Management's report > Financial review",
        "Management's report > Financial review",
        "Financial statements",
    ]
