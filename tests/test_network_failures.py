"""Network failure edge case tests (mock level).

Tests application behavior when Redis, database, or external services
are unavailable. Uses mocks to simulate failures at the Python level.

No toxiproxy or TCP-level tests -- the app has no resilience logic
beyond basic fail-open/silent-catch patterns, so mocks are sufficient.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError


class TestRedisFailureFallback:
    """Tests for Redis failure handling across the application."""

    def test_rate_limiter_falls_back_to_memory(self, client, app, real_rate_limiter):
        """Rate limiter in-memory fallback actually enforces the limit.

        When Redis is unavailable (fallback mode), the in-memory limiter
        must still enforce per-minute caps. Sends 12 requests with a
        limit of 10/min and asserts the exact pattern: [True]*10 + [False]*2.
        """
        import app.shared.core.rate_limiter as rl

        # Save original state
        orig_client = rl._redis_client
        orig_fallback = rl._fallback_mode

        try:
            # Simulate Redis unavailable -- force the in-memory branch
            rl._redis_client = None
            rl._fallback_mode = True
            rl.clear("org_test_fallback")

            results = []
            for _i in range(12):
                allowed, _info = rl.check_rate_limit("org_test_fallback", 10, 100)
                results.append(allowed)

            # First 10 must be allowed, 11th and 12th must be denied
            assert results[:10] == [True] * 10, results
            assert results[10:] == [False, False], results
        finally:
            rl._redis_client = orig_client
            rl._fallback_mode = orig_fallback
            rl.clear()

    def test_rate_limiter_falls_back_to_memory_when_redis_fails_mid_request(
        self, real_rate_limiter
    ):
        """When Redis fails mid-request, the rate limiter falls back to
        in-memory limiting instead of allowing all requests (L-2 fix).

        _check_redis catches (RedisError, ConnectionError, OSError) and
        delegates to _check_memory, so rate limiting is still enforced
        even when Redis is unreachable.

        This test sends 15 requests with a limit of 10/min and verifies
        that only the first 10 are allowed -- the in-memory fallback
        correctly enforces the limit.
        """
        import app.shared.core.rate_limiter as rl

        # Save original state
        orig_client = rl._redis_client
        orig_fallback = rl._fallback_mode

        try:
            # Set up a mock Redis client that raises on every pipeline operation
            # _fallback_mode must be False so _check_redis is called (not _check_memory)
            mock_redis = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.zremrangebyscore.side_effect = ConnectionError("Redis down")
            mock_redis.pipeline.return_value = mock_pipeline
            mock_redis.__bool__ = lambda self: True  # truthiness check

            rl._redis_client = mock_redis
            rl._fallback_mode = False
            rl.clear("org_fallback_test")  # clear specific key to avoid scan

            # Send 15 requests with a limit of 10/minute, 100/day
            results = []
            for _i in range(15):
                allowed, info = rl.check_rate_limit("org_fallback_test", 10, 100)
                results.append(allowed)

            # First 10 should be allowed, remaining 5 should be denied
            assert results[:10] == [True] * 10, (
                f"Expected first 10 requests allowed, got {results[:10]}"
            )
            assert results[10:] == [False] * 5, (
                f"Expected last 5 requests denied by in-memory fallback, but got {results[10:]}"
            )
        finally:
            rl._redis_client = orig_client
            rl._fallback_mode = orig_fallback
            rl.clear()

    def test_ws_pubsub_failure_silent(self):
        """WebSocket event publishing fails silently on Redis error.

        _publish_ws_event catches all exceptions and logs at debug level.
        It never raises, ensuring Celery task execution is not interrupted
        by Redis failures.
        """
        mock_client = MagicMock()
        mock_client.publish.side_effect = OSError("Connection reset by peer")

        with patch(
            "app.domains.solver.tasks.solve_tasks._get_redis_client", return_value=mock_client
        ):
            from app.domains.solver.tasks.solve_tasks import _publish_ws_event

            # Should not raise
            result = _publish_ws_event(
                "exe_test789",
                {
                    "type": "progress",
                    "progress": 0.5,
                },
            )
            # _publish_ws_event returns None (implicit)
            assert result is None


class TestDatabaseConnectionFailure:
    """Tests for database connection failure handling."""

    def test_api_returns_error_on_db_connection_error(
        self, client, app, db_session, test_organization, test_user, mock_auth
    ):
        """API raises error (not hang) when DB connection fails mid-request.

        When get_db raises OperationalError, the exception propagates up
        through FastAPI. The important behavior is that the request does
        NOT hang -- it either returns an error status or raises an exception.
        """
        mock_auth(test_user)

        # Patch the db dependency to raise OperationalError
        def broken_db():
            raise OperationalError(
                "connection refused",
                params=None,
                orig=Exception("could not connect to server"),
            )

        from app.shared.db.base import get_db

        app.dependency_overrides[get_db] = broken_db

        try:
            # The OperationalError propagates -- verify it does NOT hang
            with pytest.raises(OperationalError):
                client.get("/api/v2/credits/balance")
        finally:
            # Restore normal DB dependency
            app.dependency_overrides[get_db] = lambda: db_session

    def test_partial_response_on_timeout(
        self, client, app, db_session, test_organization, test_user, mock_auth
    ):
        """API never returns 2xx with partial data when a DB query times out.

        Hard contract: status code must be either a non-2xx error OR a precise
        sentinel error code, never a successful response with body. Asserting
        only `>= 400 or == 200` (the previous formulation) covered 100% of HTTP
        codes and asserted nothing.
        """
        from starlette.testclient import TestClient

        mock_auth(test_user)

        # Patch db_session.query to raise TimeoutError on every call -- the
        # first attempted DB lookup inside the endpoint must trip it.
        def raise_timeout(*args, **kwargs):
            raise TimeoutError("Statement timed out")

        non_raising_client = TestClient(app, raise_server_exceptions=False)
        with patch.object(db_session, "query", side_effect=raise_timeout):
            resp = non_raising_client.get("/api/v2/organizations/org_test001")

        # Hard contract: must NEVER return a successful body on DB timeout.
        assert resp.status_code not in (200, 201, 204), (
            f"Endpoint must not return success body on DB timeout, got {resp.status_code}"
        )
        # Must be an error response of some kind (4xx or 5xx, not 3xx redirect)
        assert resp.status_code >= 400, (
            f"Expected an error response on DB timeout, got {resp.status_code}"
        )


class TestExternalServiceFailure:
    """Tests for external service unavailability."""

    def test_stripe_service_unavailable(
        self, client, app, db_session, test_organization, test_user, mock_auth
    ):
        """Billing endpoint returns 503 when Stripe is not configured.

        The _require_stripe() guard raises HTTPException(503) when
        Stripe is not configured, providing a clean error instead of
        an unhandled exception.
        """
        mock_auth(test_user)

        # Patch StripeService.is_configured to return False
        with patch(
            "app.services.stripe_service.StripeService.is_configured",
            return_value=False,
        ):
            resp = client.post(
                "/api/v2/billing/checkout/subscription",
                json={
                    "plan": "pro",
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            # Should get 503 (Stripe not configured) rather than 500
            assert resp.status_code == 503
            assert "Stripe" in resp.json().get("detail", "")

    def test_anthropic_client_factory_requires_api_key(
        self, client, app, db_session, test_organization, test_user, mock_auth
    ):
        """get_anthropic_client raises a clear ValueError when no key is set.

        Renamed from test_anthropic_api_timeout (the previous name promised
        timeout testing but the body only verified the API-key absence path).
        We assert the exact ValueError message so a regression that swallows
        the missing-key case (returning None/MagicMock) fails loudly.
        """
        mock_auth(test_user)

        from app.services.llm.anthropic_client import (
            clear_client_cache,
            get_anthropic_client,
        )

        clear_client_cache()
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
            get_anthropic_client(db=None)
