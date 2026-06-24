"""Knowledge base indexing pipeline.

Extracts documents from templates, generators, and RAG data files,
embeds them with sentence-transformers, and upserts to Qdrant. Fully idempotent —
safe to run at any time.

Usage:
    python scripts/index_knowledge.py       # CLI
    celery task: rag.reindex                # Celery
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from app.services.rag.config import (
    COLLECTION_NAME,
    DENSE_VECTOR_SIZE,
    EMBEDDING_BATCH_SIZE,
)

logger = logging.getLogger(__name__)


def _deterministic_uuid(string_id: str) -> str:
    """Convert a string ID to a deterministic UUID5 for Qdrant.

    Qdrant requires integer or UUID point IDs. We use UUID5
    (namespace + string) for idempotent upserts — same string
    always produces the same UUID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, string_id))


def ensure_collection_exists(
    qdrant_client: Any,
    vector_size: int = DENSE_VECTOR_SIZE,
) -> None:
    """Create the knowledge collection if it does not exist.

    Uses synchronous Qdrant client for setup operations.
    vector_size defaults to 384 (bge-small-en-v1.5) but adapts to the
    active embedding model.
    """
    from qdrant_client.models import Distance, SparseVectorParams, VectorParams

    collections = qdrant_client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)

    if not exists:
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(),
            },
        )
        logger.info("Created collection: %s (vector_size=%d)", COLLECTION_NAME, vector_size)
    else:
        logger.info("Collection already exists: %s", COLLECTION_NAME)


async def run_full_index(
    qdrant_client: Any,
    embed_client: Any,
    templates_dir: Path | None = None,
    generators_dir: Path | None = None,
) -> dict[str, int]:
    """Run the full indexing pipeline. Idempotent — safe to repeat.

    Args:
        qdrant_client: Synchronous QdrantClient (for upserts).
        embed_client: SentenceTransformerClient (for embeddings).
        templates_dir: Override path to YAML templates directory.
        generators_dir: Override path to generators directory.

    Returns:
        Dict with total_docs, total_tokens, duration_ms.
    """
    from qdrant_client.models import PointStruct

    from app.services.rag.document_types import extract_all_documents

    start = time.monotonic()

    documents = extract_all_documents(templates_dir, generators_dir)
    if not documents:
        logger.warning("No documents extracted — nothing to index")
        return {"total_docs": 0, "total_tokens": 0, "duration_ms": 0}

    total_tokens = 0
    loop = asyncio.get_running_loop()

    for i in range(0, len(documents), EMBEDDING_BATCH_SIZE):
        batch = documents[i : i + EMBEDDING_BATCH_SIZE]
        texts = [doc["text"] for doc in batch]

        # sentence-transformers is CPU-bound — offload to thread pool
        result = await loop.run_in_executor(
            None,
            functools.partial(
                embed_client.embed,
                texts=texts,
                input_type="document",
            ),
        )
        total_tokens += result.total_tokens

        points = [
            PointStruct(
                id=_deterministic_uuid(doc["id"]),
                vector={"dense": embedding},
                payload={**doc["payload"], "text": doc["text"], "doc_id": doc["id"]},
            )
            for doc, embedding in zip(batch, result.embeddings, strict=True)
        ]

        await loop.run_in_executor(
            None,
            functools.partial(
                qdrant_client.upsert,
                collection_name=COLLECTION_NAME,
                wait=True,
                points=points,
            ),
        )

        batch_end = min(i + EMBEDDING_BATCH_SIZE, len(documents))
        logger.info(
            "Indexed batch %d-%d (%d tokens)",
            i + 1,
            batch_end,
            result.total_tokens,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Indexing complete: %d docs, %d tokens, %dms",
        len(documents),
        total_tokens,
        duration_ms,
    )

    return {
        "total_docs": len(documents),
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
    }


def run_full_index_sync(
    qdrant_client: Any,
    embed_client: Any,
    templates_dir: Path | None = None,
    generators_dir: Path | None = None,
) -> dict[str, int]:
    """Synchronous wrapper for ``run_full_index``. For CLI and Celery."""
    return asyncio.run(
        run_full_index(
            qdrant_client,
            embed_client,
            templates_dir,
            generators_dir,
        )
    )
