"""Load the local embedding model and reranker once, on the GPU when there is one.

The models come from Hugging Face on first use and are cached there afterwards. On a GPU they run in half precision,
which halves memory and time; on the eval questions the reranked order is identical to full precision.
"""

from __future__ import annotations

from functools import cache, lru_cache

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

from bankrag.config import EMBED_MODEL, RERANK_MODEL

MAX_TOKENS = 1024  # the longest chunks (whole tables) are about 1,200 tokens; longer inputs cost more than they add
BATCH_SIZE = 16


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _model_kwargs() -> dict[str, torch.dtype]:
    return {"dtype": torch.float16} if _device() == "cuda" else {}


@cache
def _embedder() -> SentenceTransformer:
    model = SentenceTransformer(EMBED_MODEL, device=_device(), model_kwargs=_model_kwargs())
    model.max_seq_length = MAX_TOKENS
    return model


@cache
def _reranker() -> CrossEncoder:
    model: CrossEncoder = CrossEncoder(
        RERANK_MODEL,
        device=_device(),
        max_length=MAX_TOKENS,
        model_kwargs=_model_kwargs(),
    )
    return model


def embed_documents(texts: list[str]) -> np.ndarray:
    """Embed passages for the index, as unit-length vectors (one row per text)."""
    vectors: np.ndarray = _embedder().encode_document(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    return vectors


@lru_cache(maxsize=4096)
def embed_query(text: str) -> tuple[float, ...]:
    """Embed a search query as a unit-length vector. Cached, because evals search the same question many times."""
    vector = _embedder().encode_query([text], normalize_embeddings=True, convert_to_numpy=True)[0]
    return tuple(float(value) for value in vector)


def rerank_scores(query: str, passages: list[str]) -> list[float]:
    """Score how well each passage answers the query, reading both together. Higher is better.

    The scores are the model's raw logits rather than the default sigmoid, which squeezes every strong match into
    0.999 and up and makes the scores in the web page unreadable. The order is the same either way.
    """
    pairs = [(query, passage) for passage in passages]
    scores = _reranker().predict(pairs, batch_size=BATCH_SIZE, activation_fn=torch.nn.Identity())
    return [float(score) for score in scores]
