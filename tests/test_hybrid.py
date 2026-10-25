"""Tests for vector search in Qdrant, rank fusion and reranking, with fake models so no model is downloaded."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from qdrant_client import QdrantClient

from bankrag.config import Bank
from bankrag.models import Chunk
from bankrag.retrieve import Hit
from bankrag.retrieve import dense as dense_module
from bankrag.retrieve.dense import DenseRetriever, build_index, index_is_current
from bankrag.retrieve.hybrid import HybridRetriever
from bankrag.retrieve.rerank import RerankedRetriever

VOCABULARY = ["profit", "capital", "impairment", "dividend"]


def chunk(chunk_id: str, bank: Bank, year: int, text: str) -> Chunk:
    page = int(chunk_id.split("-")[-1])
    return Chunk(
        id=chunk_id,
        bank=bank,
        year=year,
        page=page,
        section="",
        heading="",
        text=text,
        body=text,
        has_table=False,
    )


CHUNKS = [
    chunk("danske-2025-1", "danske", 2025, "net profit for the year"),
    chunk("danske-2024-2", "danske", 2024, "net profit for the year"),
    chunk("nordea-2025-3", "nordea", 2025, "capital ratio and dividend"),
    chunk("jyske-2025-4", "jyske", 2025, "loan impairment charges"),
]


def fake_vector(text: str) -> np.ndarray:
    """A bag-of-words vector over a tiny vocabulary, enough to make similar texts close."""
    vector = np.array([float(word in text) for word in VOCABULARY]) + 0.01
    return vector / np.linalg.norm(vector)


def fake_embed_documents(texts: list[str]) -> np.ndarray:
    return np.stack([fake_vector(text) for text in texts])


def fake_embed_query(text: str) -> tuple[float, ...]:
    return tuple(float(value) for value in fake_vector(text))


class TestDenseRetriever:
    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> QdrantClient:
        monkeypatch.setattr(dense_module, "FINGERPRINT_FILE", tmp_path / "fingerprint.json")
        client = QdrantClient(":memory:")
        build_index(client, CHUNKS, fake_embed_documents)
        return client

    def test_nearest_chunk_comes_first(self, client: QdrantClient) -> None:
        hits = DenseRetriever(CHUNKS, client, fake_embed_query).search("What was the profit?", k=2)
        assert hits[0].chunk.id in {"danske-2025-1", "danske-2024-2"}

    def test_bank_and_year_filters(self, client: QdrantClient) -> None:
        retriever = DenseRetriever(CHUNKS, client, fake_embed_query)
        hits = retriever.search("profit", k=4, banks=["danske"], years=[2024])
        assert [hit.chunk.id for hit in hits] == ["danske-2024-2"]

    def test_index_is_current_until_the_chunks_change(self, client: QdrantClient) -> None:
        assert index_is_current(client, CHUNKS)
        changed = [*CHUNKS[:-1], chunk("jyske-2025-4", "jyske", 2025, "loan impairment charges, restated")]
        assert not index_is_current(client, changed)


class FixedRetriever:
    """Returns a fixed ranking of chunks, whatever the query."""

    def __init__(self, chunk_ids: list[str]) -> None:
        """Rank these chunks in this order."""
        self.ids = chunk_ids
        self.by_id = {item.id: item for item in CHUNKS}

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        return [Hit(self.by_id[chunk_id], 1.0) for chunk_id in self.ids[:k]]


def test_fusion_favours_chunks_both_searches_find_over_one_search_s_first() -> None:
    keyword = FixedRetriever(["danske-2025-1", "nordea-2025-3", "danske-2024-2"])
    vector = FixedRetriever(["jyske-2025-4", "nordea-2025-3", "danske-2024-2"])
    hits = HybridRetriever([keyword, vector]).search("q", k=2)
    assert [hit.chunk.id for hit in hits] == ["nordea-2025-3", "danske-2024-2"]


def test_reranker_reorders_candidates_and_caches_scores() -> None:
    calls: list[int] = []

    def score_passages(query: str, passages: list[str]) -> list[float]:
        calls.append(len(passages))
        return [1.0 if "impairment" in passage else 0.0 for passage in passages]

    retriever = RerankedRetriever(FixedRetriever([item.id for item in CHUNKS]), score_passages)
    assert retriever.search("impairments?", k=1)[0].chunk.id == "jyske-2025-4"
    retriever.search("impairments?", k=3)
    assert calls == [4]
