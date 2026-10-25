"""Combine keyword and vector search with reciprocal rank fusion.

BM25 scores and cosine similarities are on different scales, so the two rankings are fused by rank instead of score:
each chunk gets 1 / (RRF_K + rank) from every ranking it appears in. A chunk that both searches rank fairly high
beats one that only one search ranks first.
"""

from __future__ import annotations

from collections import defaultdict

from bankrag.config import Bank
from bankrag.models import Chunk
from bankrag.retrieve.bm25 import Hit
from bankrag.retrieve.route import Retriever

RRF_K = 60  # the usual constant from the original RRF paper; it damps the advantage of rank 1 over rank 2
FUSION_DEPTH = 30  # how many hits each search contributes


class HybridRetriever:
    """Reciprocal rank fusion of several retrievers, typically BM25 and dense vectors."""

    def __init__(self, retrievers: list[Retriever]) -> None:
        """Fuse the rankings of these retrievers.

        Args:
            retrievers: The searches to combine. Each is asked for FUSION_DEPTH hits, or `k` if that is more.
        """
        self._retrievers = retrievers

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        """Return the `k` chunks with the highest fused score, best first."""
        depth = max(k, FUSION_DEPTH)
        scores: dict[str, float] = defaultdict(float)
        chunks: dict[str, Chunk] = {}
        for retriever in self._retrievers:
            for rank, hit in enumerate(retriever.search(query, depth, banks, years), start=1):
                scores[hit.chunk.id] += 1 / (RRF_K + rank)
                chunks[hit.chunk.id] = hit.chunk
        best = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)[:k]
        return [Hit(chunks[chunk_id], scores[chunk_id]) for chunk_id in best]
