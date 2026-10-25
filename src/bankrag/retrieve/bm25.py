"""Keyword search with BM25 over the chunks.

Builds the index in memory from the chunk file: about 5,000 chunks index in
under a second, so there is nothing to cache yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import bm25s
import numpy as np

from bankrag.ingest.chunk import Chunk

# Numbers keep their separators ("36,611", "45.5"), so a figure is one token.
TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|\w+", re.UNICODE)

STOPWORDS = frozenset(
    # English
    "a an and are as at be by did do does for from had has have how in is it its of on or "
    "that the their this to was were what when which who why will with "
    # Danish
    "af at de den der det en er et for fra har hvad hvor hvordan hvorfor i med og om på "
    "som til var".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class Hit:
    chunk: Chunk
    score: float


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.index = bm25s.BM25()
        self.index.index([tokenize(c.text) for c in chunks], show_progress=False)
        self._banks = np.array([c.bank for c in chunks])
        self._years = np.array([c.year for c in chunks])

    def search(
        self,
        query: str,
        k: int = 6,
        banks: list[str] | None = None,
        years: list[int] | None = None,
    ) -> list[Hit]:
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
        k = min(k, int(mask.sum()))
        ids, scores = self.index.retrieve(
            [tokens], k=k, show_progress=False, weight_mask=mask.astype(np.float32)
        )
        return [
            Hit(self.chunks[i], float(s)) for i, s in zip(ids[0], scores[0], strict=True) if s > 0 and mask[i]
        ]
