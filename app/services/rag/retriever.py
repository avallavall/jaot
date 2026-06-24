"""RAG retriever — search the knowledge base for relevant optimization context.

Performs hybrid dense+sparse search via Qdrant with Reciprocal Rank Fusion,
caches embeddings in Redis, and formats results for prompt injection.
All operations degrade gracefully — RAG failure never blocks formulation.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
from typing import Any

from app.services.rag.config import (
    COLLECTION_NAME,
    EMBEDDING_CACHE_PREFIX,
    EMBEDDING_CACHE_TTL,
    HIGH_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Module-level async Redis singleton (avoids creating a new pool per request)
_async_redis: Any | None = None
_async_redis_attempted = False


class RAGRetriever:
    """Retrieves relevant optimization knowledge for formulation generation."""

    def __init__(
        self,
        qdrant: Any,  # AsyncQdrantClient
        embed_client: Any,  # SentenceTransformerClient
        redis: Any | None = None,  # redis.asyncio client
    ) -> None:
        self._qdrant = qdrant
        self._embed_client = embed_client
        self._redis = redis

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.35,
        category_filter: str | None = None,
        doc_type_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant documents for a query.

        Uses hybrid search (dense + sparse with RRF fusion). Requests
        top_k*2 results initially and slices down — avoids a second
        Qdrant round-trip for the dynamic expansion case.
        """
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            Fusion,
            FusionQuery,
            MatchValue,
            Prefetch,
        )

        query_vector = await self._embed_query(query)

        filter_conditions = []
        if category_filter:
            filter_conditions.append(
                FieldCondition(key="category", match=MatchValue(value=category_filter))
            )
        if doc_type_filter:
            filter_conditions.append(
                FieldCondition(key="doc_type", match=MatchValue(value=doc_type_filter))
            )
        query_filter = Filter(must=filter_conditions) if filter_conditions else None

        expanded_k = top_k * 2

        # Try hybrid search (dense + sparse with RRF), fall back to dense-only
        # if the Qdrant instance doesn't support sparse vectors (e.g., in-memory local)
        try:
            results = await self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    Prefetch(query=query_vector, using="dense", limit=expanded_k * 2),
                    Prefetch(query=query, using="sparse", limit=expanded_k * 2),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                query_filter=query_filter,
                limit=expanded_k,
                with_payload=True,
            )
        except Exception as e:
            logger.debug("Hybrid search failed, falling back to dense-only: %s", e)
            results = await self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                using="dense",
                query_filter=query_filter,
                limit=expanded_k,
                with_payload=True,
            )

        # Slice to top_k unless top score is below confidence threshold
        points = results.points
        if points and points[0].score >= HIGH_CONFIDENCE_THRESHOLD:
            points = points[:top_k]

        filtered = [
            {
                "text": point.payload.get("text", ""),
                "score": point.score,
                "payload": point.payload,
            }
            for point in points
            if point.score >= min_score
        ]

        logger.info(
            "RAG retrieval: query=%s..., results=%d/%d, top_score=%.3f",
            query[:50],
            len(filtered),
            len(results.points),
            filtered[0]["score"] if filtered else 0.0,
        )

        return filtered

    async def _embed_query(self, text: str) -> list[float]:
        """Embed query text, using Redis cache when available."""
        if self._redis is not None:
            cached = await self._get_cached_embedding(text)
            if cached is not None:
                return cached

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            functools.partial(
                self._embed_client.embed,
                texts=[text],
                input_type="query",
            ),
        )
        embedding = result.embeddings[0]

        if self._redis is not None:
            await self._cache_embedding(text, embedding)

        return embedding

    async def _get_cached_embedding(self, text: str) -> list[float] | None:
        """Look up a cached embedding by query text hash."""
        key = self._cache_key(text)
        try:
            cached = await self._redis.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            logger.warning("Redis cache read failed for key %s", key, exc_info=True)
        return None

    async def _cache_embedding(self, text: str, embedding: list[float]) -> None:
        """Store an embedding in Redis with TTL."""
        key = self._cache_key(text)
        try:
            await self._redis.set(key, json.dumps(embedding), ex=EMBEDDING_CACHE_TTL)
        except Exception:
            logger.warning("Redis cache write failed for key %s", key, exc_info=True)

    @staticmethod
    def _cache_key(text: str) -> str:
        """Deterministic cache key from query text."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return f"{EMBEDDING_CACHE_PREFIX}{text_hash}"


def build_search_query(
    user_message: str,
    current_formulation: dict[str, Any] | None = None,
) -> str:
    """Build the search query for RAG retrieval.

    For initial messages, uses the raw user message.
    For refinement messages, prepends problem context for better retrieval.
    """
    if current_formulation and _is_refinement_message(user_message):
        problem_name = current_formulation.get("problem_name", "")
        variables = current_formulation.get("variables", [])
        var_types = ", ".join(sorted({v.get("type", "") for v in variables if v.get("type")}))
        return (
            f"Optimization problem: {problem_name}. "
            f"Variables: {var_types}. "
            f"Modification: {user_message}"
        )
    return user_message


def _is_refinement_message(message: str) -> bool:
    """Heuristic: detect if a message is modifying an existing formulation.

    False positives are harmless (slightly richer search query).
    False negatives just use the raw message — still works.
    """
    lower = message.lower()
    modification_prefixes = (
        "add ",
        "remove ",
        "change ",
        "modify ",
        "update ",
        "replace ",
        "increase ",
        "decrease ",
        "set ",
        "make ",
        "delete ",
        "drop ",
    )
    if lower.startswith(modification_prefixes):
        return True
    modification_phrases = ["what if", "instead of", "can you add", "can you change"]
    return any(phrase in lower for phrase in modification_phrases)


async def get_rag_context(
    user_message: str,
    db: Any,
    *,
    current_formulation: dict[str, Any] | None = None,
    category_filter: str | None = None,
) -> str | None:
    """Get RAG context for the formulation system prompt.

    Checks feature flag, circuit breaker, retrieves documents, and
    formats them for prompt injection. Returns None on any failure
    (graceful degradation to no-RAG behavior).
    """
    from app.services.platform_settings_service import PlatformSettingsService as PSS
    from app.services.rag.client import (
        get_circuit_breaker,
        get_embed_client,
        get_qdrant_client,
    )

    # Batch-read all RAG settings in one DB query
    rag_settings = PSS.get_many(db, ["RAG_ENABLED", "RAG_TOP_K", "RAG_MIN_SCORE"])

    if rag_settings.get("RAG_ENABLED", "false").lower() != "true":
        return None

    cb = get_circuit_breaker()
    if cb.is_open:
        logger.debug("RAG circuit breaker is open, skipping retrieval")
        return None

    qdrant = get_qdrant_client()
    embed_client = get_embed_client()
    if qdrant is None or embed_client is None:
        return None

    try:
        redis_client = _get_async_redis()

        top_k = int(rag_settings.get("RAG_TOP_K", "5"))
        min_score = float(rag_settings.get("RAG_MIN_SCORE", "0.35"))

        retriever = RAGRetriever(
            qdrant=qdrant,
            embed_client=embed_client,
            redis=redis_client,
        )

        query = build_search_query(user_message, current_formulation)

        results = await retriever.retrieve(
            query,
            top_k=top_k,
            min_score=min_score,
            category_filter=category_filter,
        )

        cb.record_success()

        if not results:
            return None

        from app.services.llm.prompt_templates import format_rag_context

        return format_rag_context(results)

    except Exception as e:
        cb.record_failure()
        logger.error("RAG retrieval failed, falling back to no-RAG: %s", e)
        return None


def _get_async_redis() -> Any | None:
    """Get the singleton async Redis client for embedding cache."""
    global _async_redis, _async_redis_attempted

    if _async_redis is not None:
        return _async_redis
    if _async_redis_attempted:
        return None

    from app.config import settings

    if not settings.REDIS_URL:
        _async_redis_attempted = True
        return None

    try:
        import redis.asyncio as aioredis

        _async_redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
        )
        _async_redis_attempted = True
        return _async_redis
    except Exception:
        _async_redis_attempted = True
        return None
