"""Keyword search with BM25 over the chunks.

The index is built in memory from the chunk file: about 5,000 chunks index in under a second, so there is nothing to
cache.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import bm25s
import numpy as np

from bankrag.config import Bank
from bankrag.models import Chunk

# Numbers keep their separators ("36,611", "45.5"), so a figure is one token.
TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|\w+")

STOPWORDS = frozenset(
    # English
    "a an and are as at be by did do does for from had has have how in is it its of on or "
    "that the their this to was were what when which who why will with "
    # Danish
    "af at de den der det en er et for fra har hvad hvor hvordan hvorfor i med og om på "
    "som til var".split(),
)


def tokenize(text: str) -> list[str]:
    """Split text into lower-case search terms, keeping figures whole and dropping stopwords."""
    return [token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS]


@dataclass(frozen=True)
class Hit:
    """A retrieved chunk and its search score. Scores are only comparable within one search."""

    chunk: Chunk
    score: float


class BM25Retriever:
    """BM25 over the chunks' text, with optional filters on bank and year."""

    def __init__(self, chunks: list[Chunk]) -> None:
        """Index the chunks.

        Args:
            chunks: The chunks to search, from `bankrag.ingest.load_chunks`.
        """
        self.chunks = chunks
        self.index = bm25s.BM25()
        self.index.index([tokenize(chunk.text) for chunk in chunks], show_progress=False)
        self._banks = np.array([chunk.bank for chunk in chunks])
        self._years = np.array([chunk.year for chunk in chunks])

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        """Return up to `k` chunks that match the query, best first.

        Args:
            query: Free text. Only terms that appear in the chunks count.
            k: Maximum number of hits.
            banks: Only search these banks' reports, if given.
            years: Only search these years' reports, if given.

        Returns:
            Hits with a score above zero, so fewer than `k` when few chunks share a term with the query.
        """
        tokens = tokenize(query)
        if not tokens:
            return []
        mask = np.ones(len(self.chunks), dtype=bool)
        if banks:
            mask &= np.isin(self._banks, banks)
        if years:
            mask &= np.isin(self._years, years)
        if not mask.any():
            return []
        ids, scores = self.index.retrieve(
            [tokens],
            k=min(k, int(mask.sum())),
            show_progress=False,
            weight_mask=mask.astype(np.float32),
        )
        return [
            Hit(self.chunks[i], float(score))
            for i, score in zip(ids[0], scores[0], strict=True)
            if score > 0 and mask[i]
        ]
