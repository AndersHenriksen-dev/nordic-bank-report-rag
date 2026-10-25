"""Rerank search candidates with a cross-encoder, which reads the question and each passage together.

Retrieval models embed the question and the passage separately, which is fast but blurs details such as which year a
figure belongs to. A cross-encoder reads both at once and judges the pair, which is slower, so it only reranks the top
candidates of a cheaper search.
"""

from __future__ import annotations

from collections.abc import Callable

from bankrag.config import Bank
from bankrag.retrieve.bm25 import Hit
from bankrag.retrieve.route import Retriever

CANDIDATES = 30

ScorePassages = Callable[[str, list[str]], list[float]]


class RerankedRetriever:
    """Takes the top CANDIDATES hits of another retriever and reorders them with a cross-encoder."""

    def __init__(self, base: Retriever, score_passages: ScorePassages) -> None:
        """Rerank another retriever's candidates.

        Args:
            base: The search that proposes candidates.
            score_passages: Scores (query, passages) pairs; higher means a better answer to the query.
        """
        self._base = base
        self._score_passages = score_passages
        self._scores: dict[tuple[str, str], float] = {}  # (query, chunk id): evals ask the same question many times

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        """Return the `k` best of the base retriever's top CANDIDATES, by cross-encoder score."""
        candidates = self._base.search(query, max(k, CANDIDATES), banks, years)
        unscored = [hit for hit in candidates if (query, hit.chunk.id) not in self._scores]
        if unscored:
            new_scores = self._score_passages(query, [hit.chunk.text for hit in unscored])
            for hit, score in zip(unscored, new_scores, strict=True):
                self._scores[(query, hit.chunk.id)] = score
        ranked = sorted(candidates, key=lambda hit: self._scores[(query, hit.chunk.id)], reverse=True)[:k]
        return [Hit(hit.chunk, self._scores[(query, hit.chunk.id)]) for hit in ranked]
