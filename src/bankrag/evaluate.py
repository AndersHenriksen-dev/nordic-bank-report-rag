"""Metrics for the eval set: retrieval recall and MRR, number matching and citation checks."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import TypeAdapter

from bankrag.figures import close_to, figure_tokens, numbers_in, ungrounded_figures
from bankrag.models import Chunk, Question, RetrievalScores, Source
from bankrag.retrieve import Retriever, routed_search

K_VALUES = (1, 3, 6, 10)
SEARCH_DEPTH = 30  # how far down the ranking MRR looks

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


def score_retrieval(
    retriever: Retriever,
    question: Question,
    route: bool = True,
    expand: bool = True,
) -> RetrievalScores:
    """Search for one question at each k in `K_VALUES` and score the results against its evidence.

    Args:
        retriever: The search backend.
        question: An answerable question.
        route: Filter on the banks and years the question names, as `routed_search` does.
        expand: Add English wording for Danish finance terms, as `routed_search` does.

    Returns:
        Recall at each k, and the reciprocal rank of the first gold page within `SEARCH_DEPTH` results.
    """
    recall = {}
    for k in K_VALUES:
        # Search at each k, because routing splits k between banks: the top k of a deeper search is not what the
        # answer model would get.
        hits = routed_search(retriever, question.question, k=k, route=route, expand=expand)
        recall[k] = retrieval_scores(question, [page_key(hit.chunk) for hit in hits], k)[0]
    hits = routed_search(retriever, question.question, k=SEARCH_DEPTH, route=route, expand=expand)
    ranked_pages = list(dict.fromkeys(page_key(hit.chunk) for hit in hits))
    return RetrievalScores(recall=recall, reciprocal_rank=retrieval_scores(question, ranked_pages, SEARCH_DEPTH)[1])


def numbers_match(question: Question, answer_text: str) -> bool | None:
    """Check that every required figure appears in the answer, within rounding.

    Returns:
        None if the question has no required figures.
    """
    if not question.numbers:
        return None
    found = numbers_in(answer_text)
    return all(any(close_to(number, alt) for number in found for alt in alts) for alts in question.numbers)


def figures_grounded(answer_text: str, sources: list[Source]) -> bool | None:
    """Check that every figure in an answer appears in a passage the answer cites, as `ungrounded_figures` defines it.

    Returns:
        None if the answer states no figures.
    """
    if not figure_tokens(answer_text):
        return None
    return not ungrounded_figures(answer_text, [passage for source in sources for passage in source.cited_text])


def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (nearest rank), or 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))]
