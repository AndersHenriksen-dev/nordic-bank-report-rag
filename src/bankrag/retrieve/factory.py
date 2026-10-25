"""Build a retriever by name: keyword, vector, hybrid, or hybrid with reranking."""

from __future__ import annotations

from typing import Literal

from bankrag.models import Chunk
from bankrag.retrieve.bm25 import BM25Retriever
from bankrag.retrieve.dense import DenseRetriever, build_index, index_is_current, open_index
from bankrag.retrieve.hybrid import HybridRetriever
from bankrag.retrieve.neural import embed_documents, embed_query, rerank_scores
from bankrag.retrieve.rerank import RerankedRetriever
from bankrag.retrieve.route import Retriever

RetrieverKind = Literal["bm25", "dense", "hybrid", "hybrid-rerank"]
RETRIEVER_KINDS: tuple[RetrieverKind, ...] = ("bm25", "dense", "hybrid", "hybrid-rerank")
DEFAULT_RETRIEVER: RetrieverKind = "hybrid-rerank"


def ensure_index(chunks: list[Chunk]) -> bool:
    """Build the vector index unless it already holds exactly these chunks.

    Returns:
        True if the index was (re)built.
    """
    client = open_index()
    if index_is_current(client, chunks):
        return False
    build_index(client, chunks, embed_documents)
    return True


def _dense(chunks: list[Chunk]) -> DenseRetriever:
    client = open_index()
    if not index_is_current(client, chunks):
        raise SystemExit("The vector index is missing or out of date. Run `bankrag ingest` to build it.")
    return DenseRetriever(chunks, client, embed_query)


def build_retriever(kind: RetrieverKind, chunks: list[Chunk]) -> Retriever:
    """Build a retriever over the chunks. The models load on the first search, not here.

    Raises:
        SystemExit: If a vector search is asked for and the index is missing or out of date.
    """
    if kind == "bm25":
        return BM25Retriever(chunks)
    dense = _dense(chunks)
    if kind == "dense":
        return dense
    hybrid = HybridRetriever([BM25Retriever(chunks), dense])
    return hybrid if kind == "hybrid" else RerankedRetriever(hybrid, rerank_scores)
