"""Tests for the eval metrics: number matching in both number formats, recall and figure grounding."""

from __future__ import annotations

from bankrag.evaluate import figures_grounded, numbers_match, retrieval_scores
from bankrag.figures import numbers_in
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


def test_numbers_in_skips_readings_that_are_not_numbers() -> None:
    assert numbers_in("EUR 1,022.3m") == {1022.3}
    assert numbers_in("DKK 1.022,3 mio.") == {1022.3}


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


class TestFiguresGrounded:
    def test_figure_in_a_cited_passage(self) -> None:
        assert figures_grounded("The CET1 ratio was 17.3% [1].", [source(32, ["CET1 capital ratio | 17.3 | 17.8"])])

    def test_figure_missing_from_cited_passages(self) -> None:
        assert not figures_grounded("The CET1 ratio was 18.1% [1].", [source(32, ["CET1 capital ratio | 17.3"])])

    def test_rounded_restatement_in_billions(self) -> None:
        assert figures_grounded("Net profit was DKK 23.0 billion.", [source(10, ["Net profit | 23,037 | 23,629"])])

    def test_wrong_rounding_is_not_grounded(self) -> None:
        assert not figures_grounded("The ratio was 45.6%.", [source(4, ["Cost/income ratio | 45.5"])])

    def test_difference_between_stated_figures(self) -> None:
        passage = ["Cost/income ratio (%) | 45.5 | 45.6"]
        assert figures_grounded("45.5% in 2025 against 45.6% in 2024, down 0.1 points.", [source(4, passage)])

    def test_danish_number_format(self) -> None:
        assert figures_grounded("Egenkapitalforrentningen var 15,5 %.", [source(40, ["Return on equity was 15.5%"])])

    def test_years_pages_and_markers_are_not_figures(self) -> None:
        assert figures_grounded("In 2025, see page 262 [3].", []) is None

    def test_note_numbers_and_product_names_are_not_figures(self) -> None:
        assert figures_grounded("The G41 table and Microsoft 365 Copilot are mentioned.", []) is None

    def test_change_across_zero(self) -> None:
        passage = ["Loan impairment charges | 294 | -543"]
        text = "A charge of DKK 294 million against a reversal of DKK 543 million, a change of DKK 837 million."
        assert figures_grounded(text, [source(10, passage)])
