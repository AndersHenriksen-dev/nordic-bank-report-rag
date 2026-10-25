"""Vector search over the chunks in a local Qdrant index, with a multilingual embedding model.

Qdrant runs embedded (stored in data/index/qdrant), so there is no server or Docker to start. Embedded mode locks the
folder, so only one process can use the index at a time: stop the web page before running the evals.
"""

from __future__ import annotations

import atexit
import hashlib
import json
from collections.abc import Callable
from functools import cache

import numpy as np
from qdrant_client import QdrantClient, models

from bankrag.config import EMBED_MODEL, INDEX_DIR, Bank
from bankrag.models import Chunk
from bankrag.retrieve.bm25 import Hit

COLLECTION = "chunks"
UPLOAD_BATCH = 256
QDRANT_DIR = INDEX_DIR / "qdrant"
FINGERPRINT_FILE = INDEX_DIR / "fingerprint.json"

EmbedDocuments = Callable[[list[str]], np.ndarray]
EmbedQuery = Callable[[str], tuple[float, ...]]


@cache
def open_index() -> QdrantClient:
    """Open the embedded Qdrant index, once per process."""
    QDRANT_DIR.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(QDRANT_DIR))
    # Closing at exit releases the folder lock cleanly; left to garbage collection it fails noisily at shutdown.
    atexit.register(client.close)
    return client


def _fingerprint(chunks: list[Chunk]) -> str:
    """Identify an index by the model and the exact chunk texts it was built from."""
    digest = hashlib.sha256(EMBED_MODEL.encode())
    for chunk in chunks:
        digest.update(chunk.id.encode())
        digest.update(chunk.text.encode())
    return digest.hexdigest()


def index_is_current(client: QdrantClient, chunks: list[Chunk]) -> bool:
    """Tell whether the index holds exactly these chunks, embedded with the configured model."""
    if not FINGERPRINT_FILE.exists() or not client.collection_exists(COLLECTION):
        return False
    stored = json.loads(FINGERPRINT_FILE.read_text(encoding="utf-8")).get("fingerprint")
    return bool(stored == _fingerprint(chunks) and client.count(COLLECTION).count == len(chunks))


def build_index(client: QdrantClient, chunks: list[Chunk], embed_documents: EmbedDocuments) -> None:
    """Embed every chunk and replace the collection with the new vectors."""
    vectors = embed_documents([chunk.text for chunk in chunks])
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION,
        vectors_config=models.VectorParams(size=int(vectors.shape[1]), distance=models.Distance.COSINE),
    )
    points = [
        models.PointStruct(
            id=number,
            vector=vector.tolist(),
            payload={"chunk_id": chunk.id, "bank": chunk.bank, "year": chunk.year},
        )
        for number, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    ]
    client.upload_points(COLLECTION, points=points, batch_size=UPLOAD_BATCH)
    FINGERPRINT_FILE.write_text(
        json.dumps({"model": EMBED_MODEL, "chunks": len(chunks), "fingerprint": _fingerprint(chunks)}),
        encoding="utf-8",
    )


def _filter(banks: list[Bank] | None, years: list[int] | None) -> models.Filter | None:
    conditions: list[models.Condition] = []
    if banks:
        conditions.append(models.FieldCondition(key="bank", match=models.MatchAny(any=[str(bank) for bank in banks])))
    if years:
        conditions.append(models.FieldCondition(key="year", match=models.MatchAny(any=list(years))))
    return models.Filter(must=conditions) if conditions else None


class DenseRetriever:
    """Nearest-neighbour search on chunk embeddings, with optional filters on bank and year."""

    def __init__(self, chunks: list[Chunk], client: QdrantClient, embed_query: EmbedQuery) -> None:
        """Search an index built from these chunks.

        Args:
            chunks: The chunks the index was built from, to turn search results back into chunks.
            client: An open Qdrant client holding the index.
            embed_query: Turns a query into a vector in the same space as the indexed chunks.
        """
        self._chunks = {chunk.id: chunk for chunk in chunks}
        self._client = client
        self._embed_query = embed_query

    def search(self, query: str, k: int, banks: list[Bank] | None = None, years: list[int] | None = None) -> list[Hit]:
        """Return the `k` chunks whose embeddings are closest to the query's, best first."""
        result = self._client.query_points(
            COLLECTION,
            query=list(self._embed_query(query)),
            query_filter=_filter(banks, years),
            limit=k,
            with_payload=["chunk_id"],
        )
        return [
            Hit(self._chunks[str(point.payload["chunk_id"])], point.score) for point in result.points if point.payload
        ]
