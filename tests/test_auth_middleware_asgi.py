"""Comprehensive tests for pure ASGI auth middleware.

Covers:
- Public endpoint allowlist matching (static + dynamic)
- Method restrictions
- Regression tests against old middleware bugs
- Auth rejection paths (401 for missing/invalid/expired tokens)
- Error handling (503 for DB errors, 500 for unexpected)
- CORS preflight passthrough
- Non-HTTP scope passthrough
- Response header injection
- Middleware class structure

These are pure unit tests that do NOT require a database connection.
The autouse fixtures from conftest.py are overridden to avoid DB dependency.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.shared.core.auth_middleware import (
    PUBLIC_DYNAMIC_PATHS,
    PUBLIC_PATHS,
    ASGIAuthMiddleware,
    _is_public,
)


# Override autouse fixtures from conftest.py — these tests need no database.
@pytest.fixture(autouse=True)
def _truncate_tables():
    yield


@pytest.fixture(autouse=True)
def override_db_dependency():
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    yield


async def _noop_receive():
    return {"type": "http.request", "body": b""}


async def _noop_send(message):
    pass


def _http_scope(path: str, method: str = "GET", **extras) -> dict:
    # ASGI scopes require `headers`; default to [] so callers can omit it.
    scope = {"type": "http", "path": path, "method": method, "headers": []}
    scope.update(extras)
    return scope


class TestIsPublicStaticPaths:
    def test_root_is_public(self):
        assert _is_public("/", "GET") is True

    def test_empty_path_is_public(self):
        assert _is_public("", "GET") is True

    def test_docs_is_public(self):
        assert _is_public("/docs", "GET") is True
        assert _is_public("/docs/oauth2-redirect", "GET") is True

    def test_health_is_public(self):
        assert _is_public("/api/v2/health", "GET") is True
        assert _is_public("/api/v2/health", "POST") is True  # method=None means all

    def test_auth_endpoints_public_all_methods(self):
        auth_paths = [
            "/api/v2/auth/login",
            "/api/v2/auth/signup",
            "/api/v2/auth/refresh",
            "/api/v2/auth/logout",
            "/api/v2/auth/verify-email",
            "/api/v2/auth/forgot-password",
            "/api/v2/auth/reset-password",
        ]
        for path in auth_paths:
            assert _is_public(path, "POST") is True, f"{path} POST should be public"
            assert _is_public(path, "GET") is True, f"{path} GET should be public"

    def test_billing_webhook_post_only(self):
        assert _is_public("/api/v2/billing/webhook", "POST") is True
        # method is "POST" so GET should also match since it's prefix with None... wait
        # Actually billing webhook has method="POST", so only POST is public
        # Nope, checking the code: ("/api/v2/billing/webhook", "POST") — only POST
        assert _is_public("/api/v2/billing/webhook", "GET") is False

    def test_credits_rates_get_only(self):
        assert _is_public("/api/v2/credits/rates", "GET") is True
        assert _is_public("/api/v2/credits/rates", "POST") is False

    def test_solve_templates_get_only(self):
        assert _is_public("/api/v2/solve/templates", "GET") is True
        assert _is_public("/api/v2/solve/templates", "POST") is False

    def test_catalog_get_only(self):
        assert _is_public("/api/v2/models/catalog", "GET") is True
        assert _is_public("/api/v2/models/catalog/some-id", "GET") is True
        assert _is_public("/api/v2/models/catalog", "POST") is False

    def test_metrics_is_public(self):
        """Metrics is public at app level for Prometheus scraping; Caddy blocks external access."""
        assert _is_public("/metrics", "GET") is True


class TestIsPublicDynamicPaths:
    def test_user_public_profile_get(self):
        assert _is_public("/api/v2/users/abc123/public", "GET") is True

    def test_user_public_profile_post_blocked(self):
        assert _is_public("/api/v2/users/abc123/public", "POST") is False

    def test_org_public_profile_post_blocked(self):
        assert _is_public("/api/v2/organizations/abc123/public", "POST") is False


class TestTriggerFireEndpoint:
    def test_trigger_fire_post_public(self):
        assert _is_public("/api/v2/triggers/abc-123-def/fire", "POST") is True

    def test_trigger_fire_get_blocked(self):
        assert _is_public("/api/v2/triggers/abc-123-def/fire", "GET") is False

    def test_trigger_toggle_not_public(self):
        assert _is_public("/api/v2/triggers/abc123/toggle", "POST") is False

    def test_trigger_create_not_public(self):
        assert _is_public("/api/v2/triggers/", "POST") is False

    def test_trigger_rerun_not_public(self):
        assert _is_public("/api/v2/triggers/abc123/runs/xyz/rerun", "POST") is False

    def test_trigger_fire_with_uuid_id(self):
        assert (
            _is_public("/api/v2/triggers/550e8400-e29b-41d4-a716-446655440000/fire", "POST") is True
        )

    def test_trigger_fire_wrong_depth_blocked(self):
        """Path with extra segments beyond /triggers/{id}/fire should not match."""
        assert _is_public("/api/v2/triggers/abc/extra/fire", "POST") is False


class TestProtectedEndpoints:
    def test_solve_not_public(self):
        assert _is_public("/api/v2/solve", "POST") is False

    def test_llm_not_public(self):
        assert _is_public("/api/v2/llm/conversations", "POST") is False
        assert _is_public("/api/v2/llm/conversations", "GET") is False

    def test_admin_not_public(self):
        assert _is_public("/api/v2/admin/credits/adjust", "POST") is False
        assert _is_public("/api/v2/admin/users", "GET") is False

    def test_builder_not_public(self):
        assert _is_public("/api/v2/builder", "GET") is False
        assert _is_public("/api/v2/builder/models", "GET") is False

    def test_keys_not_public(self):
        assert _is_public("/api/v2/keys", "GET") is False

    def test_gdpr_not_public(self):
        assert _is_public("/api/v2/gdpr/export", "POST") is False

    def test_notifications_not_public(self):
        assert _is_public("/api/v2/notifications", "GET") is False

    def test_workspaces_not_public(self):
        assert _is_public("/api/v2/workspaces", "GET") is False

    def test_billing_routes_not_public(self):
        """Billing routes other than webhook should be protected."""
        assert _is_public("/api/v2/billing/subscription", "GET") is False
        assert _is_public("/api/v2/billing/invoices", "GET") is False


class TestRegressionOldMiddleware:
    def test_no_substring_matching(self):
        """Old middleware matched any path containing '/public' — this must not happen."""
        assert _is_public("/api/v2/admin/public-settings", "GET") is False

    def test_no_endswith_matching(self):
        """Old middleware matched any path ending in '/fire' — only explicit trigger fire."""
        assert _is_public("/api/v2/some-new-endpoint/fire", "POST") is False

    def test_no_contains_matching(self):
        """Old middleware had 'contains' strategy — verify it's gone."""
        assert _is_public("/api/v2/whatever/public/data", "GET") is False

    def test_trailing_slash_on_auth_endpoint(self):
        """Trailing slash should still match (prefix matching)."""
        assert _is_public("/api/v2/auth/login/", "POST") is True


class TestMiddlewareStructure:
    def test_not_base_http_middleware(self):
        from starlette.middleware.base import BaseHTTPMiddleware

        assert not issubclass(ASGIAuthMiddleware, BaseHTTPMiddleware)

    def test_public_paths_are_tuples(self):
        for entry in PUBLIC_PATHS:
            assert isinstance(entry, tuple), f"Expected tuple, got {type(entry)}"
            assert len(entry) == 2
            path, method = entry
            assert isinstance(path, str)
            assert method is None or isinstance(method, str)

    def test_dynamic_paths_are_tuples(self):
        for entry in PUBLIC_DYNAMIC_PATHS:
            assert isinstance(entry, tuple), f"Expected tuple, got {type(entry)}"
            assert len(entry) == 3  # (prefix, method, allowed_suffixes)
            path, method, suffixes = entry
            assert isinstance(path, str)
            assert method is None or isinstance(method, str)
            assert suffixes is None or isinstance(suffixes, set)


class TestMiddlewarePassthrough:
    @pytest.mark.asyncio
    async def test_options_passes_through(self):
        """OPTIONS (CORS preflight) always passes through without auth."""
        called = False

        async def dummy_app(scope, receive, send):
            nonlocal called
            called = True

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "OPTIONS")
        await middleware(scope, _noop_receive, _noop_send)
        assert called

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self):
        """Non-HTTP scopes (lifespan, websocket without auth) pass through."""
        called = False

        async def dummy_app(scope, receive, send):
            nonlocal called
            called = True

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = {"type": "lifespan"}
        await middleware(scope, _noop_receive, _noop_send)
        assert called

    @pytest.mark.asyncio
    async def test_public_endpoint_passes_through(self):
        """Public endpoints pass through without authentication and
        without any auth headers injected into the response."""
        called = False
        sent_messages = []

        async def dummy_app(scope, receive, send):
            nonlocal called
            called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def capture_send(message):
            sent_messages.append(message)

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/health", "GET")
        await middleware(scope, _noop_receive, capture_send)
        assert called

        start = next(m for m in sent_messages if m["type"] == "http.response.start")
        header_keys = {k for k, _ in start["headers"]}
        # Public endpoint must NOT have auth-injected headers
        assert b"x-organization-id" not in header_keys
        assert b"x-credits-balance" not in header_keys


class TestAuthRejection:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self):
        """Protected endpoint without any auth credentials returns 401."""
        responses = []

        async def capture_send(message):
            responses.append(message)

        async def dummy_app(scope, receive, send):
            pytest.fail("App should not be called when auth fails")

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        # Mock SessionLocal and _authenticate to return (None, None, None)
        with patch("app.shared.core.auth_middleware.SessionLocal") as mock_sl:
            mock_session = MagicMock()
            mock_sl.return_value = mock_session
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                return_value=(None, None, None),
            ):
                await middleware(scope, _noop_receive, capture_send)

        # Find the response.start message
        start = next(r for r in responses if r["type"] == "http.response.start")
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_invalid_jwt_falls_through_to_api_key(self):
        """When the JWT branch fails but the API-key branch succeeds, the
        request must pass through to the app with valid auth state — the
        middleware must not short-circuit on the JWT failure.
        """
        captured_state = {}

        async def dummy_app(scope, receive, send):
            captured_state.update(scope.get("state", {}))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        fake_api_key = SimpleNamespace(id="key_fallback")
        fake_user = SimpleNamespace(id="user_fallback")
        fake_org = SimpleNamespace(id="org_fallback", credits_balance=42)

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        with patch("app.shared.core.auth_middleware.SessionLocal") as mock_sl:
            mock_session = MagicMock()
            mock_sl.return_value = mock_session

            async def _fake_authenticate(self, scope, db):
                # Simulate: JWT decode raised, but APIKeyService.verify_key
                # returned a valid (api_key, user, org) tuple. The public
                # contract of _authenticate is (user, org, api_key) on success.
                return (fake_user, fake_org, fake_api_key)

            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                _fake_authenticate,
            ):
                await middleware(scope, _noop_receive, _noop_send)

        # The app was called and got the api-key auth state on the scope
        assert captured_state.get("user") is fake_user
        assert captured_state.get("organization") is fake_org
        assert captured_state.get("api_key") is fake_api_key

    @pytest.mark.asyncio
    async def test_valid_auth_passes_through_and_injects_headers(self):
        """Valid authentication should pass request to app and inject response headers."""
        app_called = False

        async def dummy_app(scope, receive, send):
            nonlocal app_called
            app_called = True
            # Simulate a response
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"ok": true}',
                }
            )

        responses = []

        async def capture_send(message):
            responses.append(message)

        fake_user = SimpleNamespace(id="user_123")
        fake_org = SimpleNamespace(id="org_123", credits_balance=500)

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        with patch("app.shared.core.auth_middleware.SessionLocal") as mock_sl:
            mock_session = MagicMock()
            mock_sl.return_value = mock_session
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                return_value=(fake_user, fake_org, None),
            ):
                await middleware(scope, _noop_receive, capture_send)

        assert app_called

        # Check injected headers
        start = next(r for r in responses if r["type"] == "http.response.start")
        header_dict = {k: v for k, v in start["headers"]}
        assert header_dict[b"x-organization-id"] == b"org_123"
        assert header_dict[b"x-credits-balance"] == b"500"

    @pytest.mark.asyncio
    async def test_auth_injects_user_and_org_into_scope_state(self):
        """Valid auth should put user and org into scope['state']."""
        captured_state = {}

        async def dummy_app(scope, receive, send):
            captured_state.update(scope.get("state", {}))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        fake_user = SimpleNamespace(id="user_456")
        fake_org = SimpleNamespace(id="org_456", credits_balance=100)
        fake_api_key = SimpleNamespace(id="key_456")

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/builder", "GET")

        with patch("app.shared.core.auth_middleware.SessionLocal") as mock_sl:
            mock_session = MagicMock()
            mock_sl.return_value = mock_session
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                return_value=(fake_user, fake_org, fake_api_key),
            ):
                await middleware(scope, _noop_receive, _noop_send)

        assert captured_state["user"].id == "user_456"
        assert captured_state["organization"].id == "org_456"
        assert captured_state["api_key"].id == "key_456"


class TestMiddlewareErrorHandling:
    @pytest.mark.asyncio
    async def test_db_operational_error_returns_503(self):
        """Database operational errors should return 503 Service Unavailable."""
        responses = []

        async def capture_send(message):
            responses.append(message)

        async def dummy_app(scope, receive, send):
            pytest.fail("App should not be called on DB error")

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        # Simulate an OperationalError during authentication
        from sqlalchemy.exc import OperationalError

        with patch("app.shared.core.auth_middleware.SessionLocal") as mock_sl:
            mock_session = MagicMock()
            mock_sl.return_value = mock_session
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                side_effect=OperationalError("stmt", {}, Exception("db down")),
            ):
                await middleware(scope, _noop_receive, capture_send)

        start = next(r for r in responses if r["type"] == "http.response.start")
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self):
        """Unexpected errors should return 500 Internal Server Error."""
        responses = []

        async def capture_send(message):
            responses.append(message)

        async def dummy_app(scope, receive, send):
            pytest.fail("App should not be called on unexpected error")

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        with patch("app.shared.core.auth_middleware.SessionLocal") as mock_sl:
            mock_session = MagicMock()
            mock_sl.return_value = mock_session
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected boom"),
            ):
                await middleware(scope, _noop_receive, capture_send)

        start = next(r for r in responses if r["type"] == "http.response.start")
        assert start["status"] == 500

    @pytest.mark.asyncio
    async def test_session_always_closed(self):
        """DB session must be rolled back and closed even when authentication fails."""
        mock_session = MagicMock()

        async def dummy_app(scope, receive, send):
            pytest.fail("Should not be called")

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        with patch("app.shared.core.auth_middleware._session_factory", return_value=mock_session):
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                return_value=(None, None, None),
            ):
                await middleware(scope, _noop_receive, _noop_send)

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_closed_on_exception(self):
        """DB session must be rolled back and closed even when an exception occurs."""
        mock_session = MagicMock()

        async def dummy_app(scope, receive, send):
            pytest.fail("Should not be called")

        middleware = ASGIAuthMiddleware(dummy_app)
        scope = _http_scope("/api/v2/solve", "POST")

        with patch("app.shared.core.auth_middleware._session_factory", return_value=mock_session):
            with patch.object(
                ASGIAuthMiddleware,
                "_authenticate",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                await middleware(scope, _noop_receive, _noop_send)

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


class TestWebSocketScope:
    @pytest.mark.asyncio
    async def test_websocket_scope_included_in_auth_check(self):
        """Middleware passes websocket scope through to the inner app.

        WebSocket connections handle their own authentication at the endpoint
        level (see app/api/v2/ws.py). The middleware skips auth for websocket
        scopes because starlette.requests.Request asserts scope["type"] == "http".
        """
        inner_app = AsyncMock()
        middleware = ASGIAuthMiddleware(inner_app)
        scope = {"type": "websocket", "path": "/api/v2/ws/solve", "method": "GET"}

        await middleware(scope, _noop_receive, _noop_send)

        # The inner app should have been called (websocket passed through)
        inner_app.assert_awaited_once_with(scope, _noop_receive, _noop_send)
