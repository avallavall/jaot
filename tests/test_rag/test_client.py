"""Tests for RAG client factory.

Tests the singleton pattern, graceful degradation, and helper functions.
Uses mocking since Qdrant/Voyage libraries may not be installed locally.
"""

from unittest.mock import patch

from app.services.rag.client import (
    _build_qdrant_kwargs,
    get_circuit_breaker,
    reset_clients,
)


class TestBuildQdrantKwargs:
    """Qdrant client kwargs builder respects config settings."""

    def test_default_timeout(self):
        kwargs = _build_qdrant_kwargs()
        assert kwargs["timeout"] == 5

    def test_custom_timeout(self):
        kwargs = _build_qdrant_kwargs(timeout=30)
        assert kwargs["timeout"] == 30

    @patch("app.services.rag.client.settings")
    def test_url_from_settings(self, mock_settings):
        """Qdrant URL kwarg must reflect the configured QDRANT_URL setting."""
        mock_settings.QDRANT_URL = "http://qdrant.example.test:6333"
        mock_settings.QDRANT_API_KEY = ""
        kwargs = _build_qdrant_kwargs()
        assert kwargs["url"] == "http://qdrant.example.test:6333"

    @patch("app.services.rag.client.settings")
    def test_api_key_included_when_set(self, mock_settings):
        mock_settings.QDRANT_URL = "http://qdrant:6333"
        mock_settings.QDRANT_API_KEY = "secret-key"
        kwargs = _build_qdrant_kwargs()
        assert kwargs["api_key"] == "secret-key"

    @patch("app.services.rag.client.settings")
    def test_api_key_omitted_when_empty(self, mock_settings):
        mock_settings.QDRANT_URL = "http://qdrant:6333"
        mock_settings.QDRANT_API_KEY = ""
        kwargs = _build_qdrant_kwargs()
        assert "api_key" not in kwargs


class TestCircuitBreakerSingleton:
    """Circuit breaker is always the same instance."""

    def test_returns_same_instance(self):
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is cb2


class TestResetClients:
    """Reset clears all singletons for test isolation."""

    def test_reset_clears_state(self):
        cb1 = get_circuit_breaker()
        cb1.record_failure()
        reset_clients()
        cb2 = get_circuit_breaker()
        # New instance, no failures
        assert cb2.state == "closed"
        assert cb1 is not cb2
