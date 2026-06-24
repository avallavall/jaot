"""Integration tests for the RAG retrieval pipeline.

Uses real Qdrant (in-memory mode) + FakeEmbedClient to test the full
retrieve flow: embed query → search Qdrant → filter → format.
Skipped if qdrant-client is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

# Skip entire module if qdrant-client is not installed
qdrant_client = pytest.importorskip("qdrant_client", reason="qdrant-client not installed")

from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import (  # noqa: E402
    Distance,
    PointStruct,
    SparseVectorParams,
    VectorParams,
)

from app.services.rag.config import COLLECTION_NAME, DENSE_VECTOR_SIZE  # noqa: E402
from app.services.rag.retriever import RAGRetriever  # noqa: E402
from tests.test_rag.conftest import ALL_SAMPLE_DOCS, FakeEmbedClient  # noqa: E402


@pytest.fixture
def qdrant_sync() -> QdrantClient:
    """In-memory Qdrant client for testing."""
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": VectorParams(
                size=DENSE_VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
    )
    return client


@pytest.fixture
def seeded_qdrant(qdrant_sync: QdrantClient, fake_embed: FakeEmbedClient) -> QdrantClient:
    """Qdrant with sample documents indexed using FakeEmbedClient embeddings."""
    texts = [doc["text"] for doc in ALL_SAMPLE_DOCS]
    result = fake_embed.embed(texts=texts, input_type="document")

    points = [
        PointStruct(
            id=idx,
            vector={"dense": embedding},
            payload={**doc["payload"], "text": doc["text"]},
        )
        for idx, (doc, embedding) in enumerate(zip(ALL_SAMPLE_DOCS, result.embeddings, strict=True))
    ]
    qdrant_sync.upsert(collection_name=COLLECTION_NAME, wait=True, points=points)
    return qdrant_sync


@pytest.fixture
def async_qdrant():
    """Wrap sync Qdrant in AsyncQdrantClient for retriever tests."""
    from qdrant_client import AsyncQdrantClient

    async_client = AsyncQdrantClient(":memory:")

    async def setup():
        collections = await async_client.get_collections()
        if not any(c.name == COLLECTION_NAME for c in collections.collections):
            await async_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    "dense": VectorParams(
                        size=DENSE_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                },
            )

        embed = FakeEmbedClient()
        texts = [doc["text"] for doc in ALL_SAMPLE_DOCS]
        result = embed.embed(texts=texts, input_type="document")
        points = [
            PointStruct(
                id=idx,
                vector={"dense": embedding},
                payload={**doc["payload"], "text": doc["text"]},
            )
            for idx, (doc, embedding) in enumerate(
                zip(ALL_SAMPLE_DOCS, result.embeddings, strict=True)
            )
        ]
        await async_client.upsert(collection_name=COLLECTION_NAME, wait=True, points=points)

    asyncio.run(setup())

    return async_client


# Indexer tests (sync)


class TestEnsureCollectionExists:
    """Collection creation is idempotent."""

    def test_creates_collection_when_missing(self):
        from app.services.rag.indexer import ensure_collection_exists

        client = QdrantClient(":memory:")
        ensure_collection_exists(client)
        collections = client.get_collections().collections
        assert any(c.name == COLLECTION_NAME for c in collections)

    def test_idempotent_on_existing_collection(self, qdrant_sync: QdrantClient):
        from app.services.rag.indexer import ensure_collection_exists

        # Already created by fixture
        ensure_collection_exists(qdrant_sync)  # Should not raise
        collections = qdrant_sync.get_collections().collections
        assert sum(1 for c in collections if c.name == COLLECTION_NAME) == 1


class TestFullIndexPipeline:
    """Full index pipeline embeds and upserts all documents."""

    def test_indexes_all_documents(self, qdrant_sync: QdrantClient, fake_embed: FakeEmbedClient):
        from app.services.rag.indexer import run_full_index_sync

        result = run_full_index_sync(
            qdrant_client=qdrant_sync,
            embed_client=fake_embed,
        )

        assert result["total_docs"] == 186
        assert result["total_tokens"] > 0
        assert result["duration_ms"] >= 0

        # Verify documents are in Qdrant
        collection_info = qdrant_sync.get_collection(COLLECTION_NAME)
        assert collection_info.points_count == 186

    def test_idempotent_reindex(self, qdrant_sync: QdrantClient, fake_embed: FakeEmbedClient):
        """Running index twice produces same count (upsert, not duplicate)."""
        from app.services.rag.indexer import run_full_index_sync

        run_full_index_sync(qdrant_client=qdrant_sync, embed_client=fake_embed)
        run_full_index_sync(qdrant_client=qdrant_sync, embed_client=fake_embed)

        collection_info = qdrant_sync.get_collection(COLLECTION_NAME)
        assert collection_info.points_count == 186  # Same count, not 372

    def test_embed_called_with_correct_input_type(
        self, qdrant_sync: QdrantClient, fake_embed: FakeEmbedClient
    ):
        from app.services.rag.indexer import run_full_index_sync

        run_full_index_sync(qdrant_client=qdrant_sync, embed_client=fake_embed)
        assert fake_embed.last_input_type == "document"


# Retriever integration tests (async)


class TestRetrieverRetrieve:
    """RAGRetriever.retrieve() returns relevant results from seeded Qdrant."""

    @pytest.fixture
    def retriever(self, async_qdrant, fake_embed: FakeEmbedClient) -> RAGRetriever:
        return RAGRetriever(qdrant=async_qdrant, embed_client=fake_embed)

    def test_returns_results_for_matching_query(self, retriever: RAGRetriever):
        """Query identical to a seeded doc must return that doc as the top hit."""
        results = asyncio.run(
            retriever.retrieve(
                ALL_SAMPLE_DOCS[0]["text"],
                min_score=0.0,
            )
        )
        assert len(results) > 0
        # Top-ranked result must be the exact seed document (cosine sim ~ 1.0)
        assert results[0]["text"] == ALL_SAMPLE_DOCS[0]["text"]

    def test_results_have_required_keys(self, retriever: RAGRetriever):
        results = asyncio.run(retriever.retrieve(ALL_SAMPLE_DOCS[0]["text"], min_score=0.0))
        for r in results:
            assert "text" in r
            assert "score" in r
            assert "payload" in r
            assert isinstance(r["score"], float)

    def test_results_sorted_by_score_descending(self, retriever: RAGRetriever):
        results = asyncio.run(retriever.retrieve(ALL_SAMPLE_DOCS[0]["text"], min_score=0.0))
        if len(results) > 1:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_min_score_filters_low_results(self, retriever: RAGRetriever):
        results = asyncio.run(retriever.retrieve(ALL_SAMPLE_DOCS[0]["text"], min_score=0.99))
        for r in results:
            assert r["score"] >= 0.99

    def test_top_k_limits_results(self, retriever: RAGRetriever):
        """top_k bound: retriever fetches expanded_k=top_k*2, slices to top_k.

        Documented expansion factor is 2x in retriever.retrieve, so the
        absolute upper bound on results is top_k*2 (when high-confidence
        slicing skips). For top_k=2 the cap is 4 results.
        """
        results = asyncio.run(
            retriever.retrieve(ALL_SAMPLE_DOCS[0]["text"], top_k=2, min_score=0.0)
        )
        # Either 2 (sliced when top score >= HIGH_CONFIDENCE_THRESHOLD)
        # or up to 4 (expansion fallback). Never more.
        assert len(results) <= 4
        # Identical-to-seed query yields max-confidence top hit, so the
        # high-confidence slicing kicks in and we expect exactly top_k.
        assert len(results) == 2

    def test_embed_called_with_query_input_type(self, async_qdrant, fake_embed: FakeEmbedClient):
        retriever = RAGRetriever(qdrant=async_qdrant, embed_client=fake_embed)
        asyncio.run(retriever.retrieve("test query", min_score=0.0))
        assert fake_embed.last_input_type == "query"


# Retriever with Redis cache (mock)


class TestRetrieverCache:
    """Embedding cache avoids repeated embed calls."""

    def test_second_call_uses_cache(self, async_qdrant):
        """Same query twice should only call embed once (cached)."""
        import json
        from unittest.mock import AsyncMock

        fake_embed = FakeEmbedClient()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Cache miss first time
        mock_redis.set = AsyncMock()

        retriever = RAGRetriever(qdrant=async_qdrant, embed_client=fake_embed, redis=mock_redis)

        # First call: cache miss → embed → cache set
        asyncio.run(retriever.retrieve("knapsack problem", min_score=0.0))
        assert fake_embed.call_count == 1
        mock_redis.set.assert_called_once()

        # Simulate cache hit: return the cached embedding
        cached_vec = json.dumps(fake_embed._text_to_vector("knapsack problem"))
        mock_redis.get = AsyncMock(return_value=cached_vec)

        # Second call: cache hit → no embed call
        asyncio.run(retriever.retrieve("knapsack problem", min_score=0.0))
        assert fake_embed.call_count == 1  # Still 1, not 2

    def test_cache_failure_does_not_break_retrieval(self, async_qdrant):
        """Redis errors are swallowed — retrieval continues without cache."""
        from unittest.mock import AsyncMock

        fake_embed = FakeEmbedClient()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))

        retriever = RAGRetriever(qdrant=async_qdrant, embed_client=fake_embed, redis=mock_redis)

        # Should not raise despite Redis failure
        results = asyncio.run(retriever.retrieve("knapsack problem", min_score=0.0))
        assert isinstance(results, list)
        assert fake_embed.call_count == 1  # Fell back to direct embed


# Resilience: oversized query input


class TestRagOversizedQuery:
    """Adversarial input — extremely long pasted text — must not crash."""

    def test_oversized_query_does_not_crash(self, async_qdrant):
        """A ~14KB query string must be handled without raising."""
        from tests.test_rag.conftest import FakeEmbedClient

        fake_embed = FakeEmbedClient()
        retriever = RAGRetriever(qdrant=async_qdrant, embed_client=fake_embed)

        oversized = "minimize cost " * 1000  # ~14KB
        results = asyncio.run(retriever.retrieve(oversized, min_score=0.0))
        # Must return a list (possibly empty), never raise
        assert isinstance(results, list)
