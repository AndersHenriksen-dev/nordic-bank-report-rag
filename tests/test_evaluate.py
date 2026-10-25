"""Tests for the eval metrics: number matching in both number formats, recall and citation checks."""

from __future__ import annotations

from bankrag.evaluate import citation_ok, numbers_in, numbers_match, retrieval_scores
from bankrag.models import Question, Source


def question(numbers: list[list[float]] | None = None, evidence: list[list[str]] | None = None) -> Question:
    return Question(
        id="t",
        question="?",
        lang="en",
        category="lookup",
        answerable=True,
        gold_answer="",
        numbers=numbers or [],
        evidence=evidence or [],
    )


def source(page: int, cited_text: list[str]) -> Source:
    return Source(n=1, chunk_id="c", bank="danske", year=2025, page=page, section="", cited_text=cited_text)


def test_numbers_in_reads_english_and_danish_formats() -> None:
    assert 23037.0 in numbers_in("DKK 23,037 million")
    assert 23037.0 in numbers_in("23.037 mio. kr.")
    assert 15.5 in numbers_in("15,5%")
    assert 45.5 in numbers_in("45.5%")


class TestNumbersMatch:
    def test_needs_every_figure(self) -> None:
        q = question(numbers=[[45.5], [45.6]])
        assert numbers_match(q, "45.5% in 2025 against 45.6% in 2024")
        assert not numbers_match(q, "45.5% in 2025")

    def test_accepts_alternative_units(self) -> None:
        q = question(numbers=[[23037, 23.0]])
        assert numbers_match(q, "DKK 23.0 billion")
        assert numbers_match(q, "DKK 23,037 million")
        assert not numbers_match(q, "DKK 23,629 million")

    def test_is_none_without_figures(self) -> None:
        assert numbers_match(question(), "anything") is None


def test_retrieval_scores_counts_groups() -> None:
    q = question(evidence=[["a-2025-p4", "a-2025-p5"], ["b-2025-p40"]])
    recall, reciprocal_rank = retrieval_scores(q, ["x-2025-p1", "a-2025-p5", "y-2025-p2"], k=3)
    assert recall == 0.5
    assert reciprocal_rank == 0.5


def test_citation_ok_by_page_or_quoted_figure() -> None:
    q = question(numbers=[[17.3]], evidence=[["danske-2025-p32"]])
    assert citation_ok(q, source(32, []))
    assert citation_ok(q, source(6, ["The CET1 capital ratio was 17.3%"]))
    assert not citation_ok(q, source(99, ["Net profit was DKK 23,037 million"]))
