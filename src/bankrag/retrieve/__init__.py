"""Search over the chunks: BM25, vectors in Qdrant, hybrid fusion, reranking, routing and the Danish glossary."""

from bankrag.retrieve.bm25 import BM25Retriever, Hit
from bankrag.retrieve.factory import DEFAULT_RETRIEVER, RETRIEVER_KINDS, RetrieverKind, build_retriever, ensure_index
from bankrag.retrieve.rewrite import expand_danish
from bankrag.retrieve.route import Retriever, detect_filters, routed_search

__all__ = [
    "DEFAULT_RETRIEVER",
    "RETRIEVER_KINDS",
    "BM25Retriever",
    "Hit",
    "Retriever",
    "RetrieverKind",
    "build_retriever",
    "detect_filters",
    "ensure_index",
    "expand_danish",
    "routed_search",
]
