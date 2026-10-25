"""Tests for reading bank and year filters from questions and balancing results across banks."""

from __future__ import annotations

from bankrag.config import Bank
from bankrag.models import Chunk
from bankrag.retrieve import Hit, detect_filters, routed_search


class TestDetectFilters:
    def test_single_bank_and_years(self) -> None:
        filters = detect_filters("What was Danske Bank's cost/income ratio in 2025, and how did it change from 2024?")
        assert filters.banks == ["danske"]
        assert filters.years == [2024, 2025]

    def test_danish_genitive(self) -> None:
        assert detect_filters("Hvad var Nordeas egenkapitalforrentning i 2025?").banks == ["nordea"]

    def test_all_banks(self) -> None:
        assert detect_filters("Compare the CET1 ratio of the three banks").banks == ["danske", "nordea", "jyske"]

    def test_years_outside_the_reports_are_ignored(self) -> None:
        assert detect_filters("What was Nordea's net profit in 2012?").years == []


class SkewedRetriever:
    """Returns hits for one bank per search, with Danske always scoring highest, as if its wording matched best."""

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        assert banks is not None
        bank = banks[0]
        base = {"danske": 100, "nordea": 10, "jyske": 1}[bank]
        return [Hit(_chunk(bank, page), base - page) for page in range(k)]


def _chunk(bank: Bank, page: int) -> Chunk:
    return Chunk(
        id=f"{bank}-{page}",
        bank=bank,
        year=2025,
        page=page,
        section="",
        heading="",
        text="",
        body="",
        has_table=False,
    )


def test_multi_bank_results_are_interleaved_and_cut_to_k() -> None:
    hits = routed_search(SkewedRetriever(), "Compare the CET1 ratio of the three banks", k=4)
    assert [hit.chunk.bank for hit in hits] == ["danske", "nordea", "jyske", "danske"]
