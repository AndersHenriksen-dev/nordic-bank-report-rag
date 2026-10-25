"""Metrics for the eval set: retrieval recall and MRR, number matching and citation checks."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from bankrag.models import Chunk, Question, Source

NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)*")
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


def numbers_in(text: str) -> set[float]:
    """Find every number in the text, read both the English and the Danish way.

    "23,037" and "23.037" can each mean 23037 or 23.037, so both readings are kept.
    """
    found: set[float] = set()
    for raw in NUMBER_RE.findall(text):
        for thousands, decimal in ((",", "."), (".", ",")):
            parts = raw.split(decimal)
            if len(parts) > 2:
                continue
            whole = parts[0]
            if thousands in whole and not all(len(group) == 3 for group in whole.split(thousands)[1:]):
                continue
            found.add(float(whole.replace(thousands, "") + ("." + parts[1] if len(parts) == 2 else "")))
    return found


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


def citation_ok(question: Question, source: Source) -> bool:
    """Check a cited source: it counts as correct if it is a gold page or quotes a gold figure."""
    if any(page_key(source) in group for group in question.evidence):
        return True
    quoted = numbers_in(" ".join(source.cited_text))
    return any(abs(number - alt) < 1e-6 for alts in question.numbers for alt in alts for number in quoted)


def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (nearest rank), or 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))]
