"""Metrics for the eval set: retrieval recall and MRR, number matching and citation checks."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import TypeAdapter

from bankrag.figures import figure_tokens, numbers_in
from bankrag.models import Chunk, Question, Source

NUMBER_TOLERANCE = 0.011  # allows rounding to one decimal, e.g. 45.46 matches 45.5

_QUESTIONS_ADAPTER: TypeAdapter[list[Question]] = TypeAdapter(list[Question])


def load_questions(path: Path) -> list[Question]:
    """Read and validate the eval questions from YAML."""
    return _QUESTIONS_ADAPTER.validate_python(yaml.safe_load(path.read_text(encoding="utf-8")))


def page_key(item: Chunk | Source) -> str:
    """Return the page reference used in the eval set's evidence lists, for example "nordea-2025-p40"."""
    return f"{item.bank}-{item.year}-p{item.page}"


def retrieval_scores(question: Question, ranked_pages: list[str], k: int) -> tuple[float, float]:
    """Score one ranking against a question's evidence.

    Args:
        question: An answerable question with evidence groups (one group per bank or year it needs).
        ranked_pages: Page references in rank order, as made by `page_key`.
        k: How many top entries count for recall.

    Returns:
        Recall@k (the share of evidence groups with a page in the top k) and the reciprocal rank of the first gold
        page anywhere in the ranking.
    """
    top = ranked_pages[:k]
    groups_found = sum(any(page in top for page in group) for group in question.evidence)
    recall = groups_found / len(question.evidence)
    gold = {page for group in question.evidence for page in group}
    reciprocal_rank = next((1 / (rank + 1) for rank, page in enumerate(ranked_pages) if page in gold), 0.0)
    return recall, reciprocal_rank


def numbers_match(question: Question, answer_text: str) -> bool | None:
    """Check that every required figure appears in the answer, within rounding.

    Returns:
        None if the question has no required figures.
    """
    if not question.numbers:
        return None
    found = numbers_in(answer_text)
    return all(
        any(abs(number - alt) <= NUMBER_TOLERANCE * max(1.0, abs(alt) / 100) for number in found for alt in alts)
        for alts in question.numbers
    )


def _rounds_to(value: float, decimals: int, pool: set[float]) -> bool:
    return any(abs(round(candidate, decimals) - value) < 1e-9 for candidate in pool)


def figures_grounded(answer_text: str, sources: list[Source]) -> bool | None:
    """Check that every figure in an answer appears in a passage the answer cites.

    A figure counts as grounded if a cited passage holds it at the precision the answer gives (23.0 billion matches
    23,037 million), or if it is the difference or percentage change between two other figures in the answer (a fall
    of 0.1 points from 45.6% to 45.5%). Years, numbers below 10, page and note references, product names and citation
    markers are not figures.

    Returns:
        None if the answer states no figures.
    """
    figures = figure_tokens(answer_text)
    if not figures:
        return None
    cited = {value for source in sources for passage in source.cited_text for value in numbers_in(passage)}
    cited |= {value / 1000 for value in cited}  # millions restated as billions
    stated = [value for token in figures for value, _ in token]
    # Sums cover changes across zero, such as from a reversal of 543 to a charge of 294 (figures are unsigned).
    derived = {abs(a - b) for a in stated for b in stated} | {a + b for a in stated for b in stated}
    derived |= {abs(a - b) / b * 100 for a in stated for b in stated if b}
    return all(any(_rounds_to(value, decimals, cited | derived) for value, decimals in token) for token in figures)


def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (nearest rank), or 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))]
