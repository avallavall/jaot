"""RAG client factory — singleton pattern matching ``anthropic_client.py``.

Manages the lifecycle of Qdrant (async) and embedding clients.
Returns ``None`` when RAG infrastructure is unavailable, enabling
graceful degradation to no-RAG behavior.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services.rag.circuit_breaker import RAGCircuitBreaker

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

logger = logging.getLogger(__name__)

# Module-level singletons (thread-safe init)
_qdrant_client: AsyncQdrantClient | None = None
_embed_client: object | None = None
_embedding_dimension: int = 384  # default, overridden by actual model
_circuit_breaker: RAGCircuitBreaker = RAGCircuitBreaker()
_init_lock = threading.Lock()
_init_attempted = False

# Cross-encoder reranker singleton (Lever B). Loaded lazily on first use and cached
# per model name; kept separate from the embedding client because it is gated off by
# default and only paid for when RAG_RERANKER_ENABLED is on.
_reranker: object | None = None
_reranker_model_name: str | None = None
_reranker_lock = threading.Lock()


def _build_qdrant_kwargs(timeout: int = 5) -> dict[str, Any]:
    """Build Qdrant client constructor kwargs from settings."""
    kwargs: dict[str, Any] = {
        "url": settings.QDRANT_URL,
        "timeout": timeout,
        "check_compatibility": False,
    }
    if settings.QDRANT_API_KEY:
        kwargs["api_key"] = settings.QDRANT_API_KEY
    return kwargs


def _try_init() -> bool:
    """Attempt to initialize Qdrant and embedding clients.

    Returns True if Qdrant client is ready, False otherwise.
    """
    global _qdrant_client, _embed_client, _embedding_dimension, _init_attempted

    if _init_attempted:
        return _qdrant_client is not None

    with _init_lock:
        if _init_attempted:
            return _qdrant_client is not None

        if not settings.QDRANT_URL:
            logger.info("RAG disabled: QDRANT_URL not set")
            _init_attempted = True
            return False

        try:
            from qdrant_client import AsyncQdrantClient

            _qdrant_client = AsyncQdrantClient(**_build_qdrant_kwargs())
            logger.info("Qdrant client initialized: %s", settings.QDRANT_URL)
        except Exception as e:
            logger.warning("Failed to initialize Qdrant client: %s", e)
            _init_attempted = True
            return False

        try:
            from app.services.rag.embeddings import create_embedding_client

            _embed_client, embed_dim = create_embedding_client()
            _embedding_dimension = embed_dim
            logger.info("Embedding client initialized (%d dims)", embed_dim)
        except Exception as e:
            logger.warning("Failed to initialize embedding client: %s", e)

        _init_attempted = True
        return True


def build_sync_qdrant_client(timeout: int = 30) -> Any:
    """Build a synchronous QdrantClient for CLI/Celery use."""
    from qdrant_client import QdrantClient

    return QdrantClient(**_build_qdrant_kwargs(timeout))


def get_qdrant_client() -> AsyncQdrantClient | None:
    """Get the singleton Qdrant async client, or None if unavailable."""
    _try_init()
    return _qdrant_client


def get_embed_client() -> object | None:
    """Get the singleton embedding client, or None if unavailable."""
    _try_init()
    return _embed_client


def get_reranker(model_name: str) -> Any | None:
    """Get the singleton cross-encoder reranker, loading it lazily.

    Cached per model name — a changed ``RAG_RERANKER_MODEL`` triggers a reload.
    Returns ``None`` (never raises) when sentence-transformers or the model is
    unavailable, so retrieval degrades gracefully to fusion-only ordering.
    """
    global _reranker, _reranker_model_name

    if _reranker is not None and _reranker_model_name == model_name:
        return _reranker

    with _reranker_lock:
        if _reranker is not None and _reranker_model_name == model_name:
            return _reranker
        try:
            from sentence_transformers import CrossEncoder

            _reranker = CrossEncoder(model_name)
            _reranker_model_name = model_name
            logger.info("RAG reranker loaded: %s", model_name)
        except Exception as e:
            logger.warning("Failed to load RAG reranker '%s': %s", model_name, e)
            _reranker = None
            _reranker_model_name = None
        return _reranker


def get_circuit_breaker() -> RAGCircuitBreaker:
    """Get the circuit breaker singleton (always the same instance)."""
    return _circuit_breaker


def get_embedding_dimension() -> int:
    """Get the embedding dimension of the active model."""
    _try_init()
    return _embedding_dimension


def is_rag_available() -> bool:
    """Check if RAG infrastructure is ready (Qdrant + embeddings)."""
    return _try_init() and _embed_client is not None


def reset_clients() -> None:
    """Reset all clients. Useful for testing."""
    global _qdrant_client, _embed_client, _embedding_dimension
    global _circuit_breaker, _init_attempted
    global _reranker, _reranker_model_name
    _qdrant_client = None
    _embed_client = None
    _embedding_dimension = 384
    _circuit_breaker = RAGCircuitBreaker()
    _init_attempted = False
    _reranker = None
    _reranker_model_name = None
