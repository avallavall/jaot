"""Tests for the RAG circuit breaker.

Covers the full state machine: closed → open → half_open → closed,
plus edge cases around threshold boundaries and recovery timing.
"""

import asyncio
import time
from unittest.mock import patch

from app.services.rag.circuit_breaker import RAGCircuitBreaker


class TestCircuitBreakerInitialState:
    """Circuit breaker starts in closed state and allows requests."""

    def test_starts_closed(self):
        cb = RAGCircuitBreaker()
        assert cb.state == "closed"

    def test_custom_thresholds(self):
        cb = RAGCircuitBreaker(failure_threshold=5, recovery_timeout=120)
        assert cb.state == "closed"
        # Needs 5 failures to open, not default 3
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"


class TestCircuitBreakerClosedToOpen:
    """Failures at or above threshold open the circuit."""

    def test_failures_below_threshold_stay_closed(self):
        cb = RAGCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.is_open is False

    def test_failures_at_threshold_open(self):
        cb = RAGCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True

    def test_failures_above_threshold_stay_open(self):
        cb = RAGCircuitBreaker(failure_threshold=3)
        for _ in range(10):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True

    def test_single_failure_threshold(self):
        cb = RAGCircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == "open"


class TestCircuitBreakerOpenToHalfOpen:
    """After recovery timeout, circuit transitions to half_open."""

    def test_open_stays_open_before_timeout(self):
        cb = RAGCircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        assert cb.is_open is True

    def test_open_transitions_to_half_open_after_timeout(self):
        cb = RAGCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.02)
        # Accessing is_open triggers the timeout check
        assert cb.is_open is False
        assert cb.state == "half_open"


class TestCircuitBreakerHalfOpenRecovery:
    """Success in half_open closes the circuit; failure reopens it."""

    def test_success_in_half_open_closes(self):
        cb = RAGCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        _ = cb.is_open  # transition to half_open
        cb.record_success()
        assert cb.state == "closed"
        assert cb.is_open is False

    def test_failure_in_half_open_reopens(self):
        cb = RAGCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        _ = cb.is_open  # transition to half_open
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True


class TestCircuitBreakerReset:
    """Success resets the failure counter completely."""

    def test_success_resets_failure_count(self):
        cb = RAGCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # After success, need 3 more failures to open
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"

    def test_success_from_open_state_closes(self):
        cb = RAGCircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == "open"
        cb.record_success()
        assert cb.state == "closed"


class TestRagOrchestratorBreakerIntegration:
    """End-to-end: get_rag_context records failures into the circuit breaker.

    Pins the contract: failures in the RAG pipeline must (1) never raise into
    the caller, (2) trip the breaker after the configured threshold, and (3)
    skip subsequent retrieval attempts while the breaker is open. This test
    works whether or not qdrant-client is installed by mocking the entire
    RAGRetriever class.
    """

    def test_qdrant_failure_records_breaker_failure_and_returns_none(self):
        from app.services.rag import retriever as retriever_module
        from app.services.rag.retriever import get_rag_context

        # Pristine breaker — start at the closed state
        cb = RAGCircuitBreaker(failure_threshold=2, recovery_timeout=60)

        # Mock the retriever class so retrieve() raises a Qdrant-like error.
        # This sidesteps the qdrant_client import requirement entirely.
        class _BrokenRetriever:
            def __init__(self, **kwargs):
                self.calls = 0

            async def retrieve(self, *args, **kwargs):
                self.calls += 1
                raise ConnectionError("Qdrant 503")

        broken_retriever = None

        def make_broken(**kwargs):
            nonlocal broken_retriever
            broken_retriever = _BrokenRetriever(**kwargs)
            return broken_retriever

        # Mock PSS to return RAG_ENABLED true without requiring DB seeding
        def fake_get_many(db, keys):
            return {"RAG_ENABLED": "true", "RAG_TOP_K": "5", "RAG_MIN_SCORE": "0.0"}

        sentinel_qdrant = object()
        sentinel_embed = object()

        with (
            patch(
                "app.services.platform_settings_service.PlatformSettingsService.get_many",
                side_effect=fake_get_many,
            ),
            patch("app.services.rag.client.get_circuit_breaker", return_value=cb),
            patch("app.services.rag.client.get_qdrant_client", return_value=sentinel_qdrant),
            patch("app.services.rag.client.get_embed_client", return_value=sentinel_embed),
            patch.object(retriever_module, "RAGRetriever", side_effect=make_broken),
        ):
            # Call 1 — first failure
            result1 = asyncio.run(
                get_rag_context("optimize 5 routes", db=None, current_formulation=None)
            )
            assert result1 is None  # Graceful degradation, no exception
            assert cb._failure_count == 1
            assert cb.state == "closed"

            # Call 2 — second failure trips the breaker
            result2 = asyncio.run(
                get_rag_context("optimize 5 routes", db=None, current_formulation=None)
            )
            assert result2 is None
            assert cb.state == "open"

            # Call 3 — breaker is OPEN, retrieval skipped: RAGRetriever should
            # not even be instantiated for this third request.
            calls_before = broken_retriever.calls if broken_retriever else 0
            result3 = asyncio.run(
                get_rag_context("optimize 5 routes", db=None, current_formulation=None)
            )
            assert result3 is None
            calls_after = broken_retriever.calls
            assert calls_after == calls_before, "breaker should have skipped retrieval"
