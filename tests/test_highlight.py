"""Tests for finding cited passages on a page, using a small PDF built in memory."""

from __future__ import annotations

from collections.abc import Iterator

import pymupdf
import pytest

from bankrag.ui.highlight import find_passage_rects, focus_passage


@pytest.fixture
def page() -> Iterator[pymupdf.Page]:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Return on equity")
    page.insert_text((300, 100), "15.5")
    page.insert_text((360, 100), "16.7")
    page.insert_text((50, 130), "Other ratio")
    page.insert_text((300, 130), "15.5")
    page.insert_text((50, 300), "At the end of December 2025 the CET1 capital ratio")
    page.insert_text((50, 314), "was 15.7 percent, down from 15.8 percent a year")
    page.insert_text((50, 328), "earlier, mainly because of higher risk exposure.")
    page.insert_text((50, 600), "At the end of December 2025 the bank also said")
    yield page
    doc.close()


def test_table_row_highlights_only_figures_on_the_label_line(page: pymupdf.Page) -> None:
    rects = find_passage_rects(page, "| Return on equity | 15.5 | 16.7 |")
    assert len(rects) == 3
    assert all(90 <= (rect.y0 + rect.y1) / 2 <= 102 for rect in rects)


def test_row_without_its_figures_is_not_highlighted(page: pymupdf.Page) -> None:
    assert find_passage_rects(page, "| Return on equity | 99.9 | 88.8 |") == []


def test_paragraph_ignores_a_repeated_phrase_elsewhere(page: pymupdf.Page) -> None:
    paragraph = (
        "At the end of December 2025 the CET1 capital ratio was 15.7 percent, down from 15.8 percent a year earlier, "
        "mainly because of higher risk exposure."
    )
    rects = find_passage_rects(page, paragraph)
    assert rects
    assert all(280 <= rect.y0 <= 335 for rect in rects)


def test_sentence_with_a_row_label_is_not_a_table_row() -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Income tax expense amounted to EUR -1,476m and -1,489m before.")
    assert find_passage_rects(page, "| Income tax expense | -1,476 | -1,489 | -1 |") == []
    doc.close()


def test_focus_keeps_header_and_the_rows_the_answer_uses() -> None:
    passage = "| EURm | 2025 | 2024 |\n| Net interest income | 7,167 | 7,594 |\n| Other income | 40 | 57 |"
    assert focus_passage(passage, {7167.0}) == "| EURm | 2025 | 2024 |\n| Net interest income | 7,167 | 7,594 |"
    assert focus_passage(passage, {123.0}) == passage


def test_label_only_row_is_not_highlighted(page: pymupdf.Page) -> None:
    assert find_passage_rects(page, "| Return on equity |") == []


def test_header_row_of_years_is_not_highlighted() -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "EURm")
    page.insert_text((300, 100), "2025")
    page.insert_text((360, 100), "2024")
    assert find_passage_rects(page, "| EURm | 2025 | 2024 |") == []
    doc.close()
