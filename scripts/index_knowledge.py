#!/usr/bin/env python3
"""CLI command to index the JAOT knowledge base into Qdrant.

Usage:
    python scripts/index_knowledge.py

Requires QDRANT_URL in .env.
Safe to run repeatedly — all upserts are idempotent.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    from app.config import settings

    if not settings.QDRANT_URL:
        logger.error("QDRANT_URL not set. Set it in .env or environment.")
        sys.exit(1)

    from app.services.rag.client import build_sync_qdrant_client
    from app.services.rag.embeddings import create_embedding_client
    from app.services.rag.indexer import ensure_collection_exists, run_full_index_sync

    qdrant = build_sync_qdrant_client(timeout=30)
    embed_client, embed_dim = create_embedding_client()

    logger.info("Connected to Qdrant at %s", settings.QDRANT_URL)

    ensure_collection_exists(qdrant, vector_size=embed_dim)

    result = run_full_index_sync(
        qdrant_client=qdrant,
        embed_client=embed_client,
    )

    print(
        f"\nIndexed {result['total_docs']} documents "
        f"({result['total_tokens']} tokens) "
        f"in {result['duration_ms']}ms"
    )


if __name__ == "__main__":
    main()
