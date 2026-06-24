"""Integration-style tests for the ASGIAuthMiddleware.

Tests the full middleware stack with mocked services, verifying:
- Public endpoints skip auth
- Missing/malformed auth returns 401
- Invalid API key returns 401
- Valid API key injects state and response headers
- DB errors return 503
- Unexpected errors return 500
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from sqlalchemy.exc import OperationalError
from starlette.testclient import TestClient

from app.shared.core.auth_middleware import ASGIAuthMiddleware


class DummySession:
    """Minimal session stub used by the middleware during tests."""

    def commit(self) -> None:
        """No-op commit."""

    def close(self) -> None:
        """No-op close."""


def _create_test_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, TestClient]:
    """Create a FastAPI app with ASGIAuthMiddleware and test endpoints."""
    monkeypatch.setattr(
        "app.shared.core.auth_middleware.SessionLocal",
        lambda: DummySession(),
    )

    app = FastAPI(docs_url=None, redoc_url=None)

    @app.get("/docs")
    async def docs() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v2/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/protected")
    async def protected(request: Request) -> dict[str, str | None]:
        user = getattr(request.state, "user", None)
        organization = getattr(request.state, "organization", None)
        return {
            "user_id": getattr(user, "id", None),
            "org_id": getattr(organization, "id", None),
        }

    @app.post("/api/v2/solve")
    async def solve(request: Request) -> dict[str, str | None]:
        user = getattr(request.state, "user", None)
        return {"user_id": getattr(user, "id", None)}

    app.add_middleware(ASGIAuthMiddleware)

    return app, TestClient(app)


# Override autouse DB fixtures
@pytest.fixture(autouse=True)
def _truncate_tables():
    yield


@pytest.fixture(autouse=True)
def override_db_dependency():
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    yield


@pytest.fixture
def middleware_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a test client with auth middleware."""
    _, client = _create_test_app(monkeypatch)
    return client


def test_public_endpoint_skips_auth(middleware_client: TestClient) -> None:
    response = middleware_client.get("/docs")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_health_endpoint_skips_auth(middleware_client: TestClient) -> None:
    """Health endpoint skips auth and injects no X-Organization-Id header."""
    response = middleware_client.get("/api/v2/health")
    assert response.status_code == 200
    # No auth ran for a public endpoint, so middleware must not inject
    # the X-Organization-Id header (that only happens for authenticated req).
    assert "X-Organization-Id" not in response.headers
    assert "X-Credits-Balance" not in response.headers


# Auth Rejection (401)


def test_missing_authorization_returns_401(middleware_client: TestClient) -> None:
    """Protected endpoint without auth header returns 401."""
    response = middleware_client.get("/protected")
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"


def test_malformed_authorization_returns_401(middleware_client: TestClient) -> None:
    """Single-word auth header (not 'Bearer <token>') returns 401."""
    response = middleware_client.get(
        "/protected",
        headers={"Authorization": "InvalidFormat"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_bearer_without_token_returns_401(middleware_client: TestClient) -> None:
    """'Bearer' without a token returns 401."""
    response = middleware_client.get(
        "/protected",
        headers={"Authorization": "Bearer"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_invalid_api_key_returns_401(
    middleware_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.shared.core.auth_middleware.APIKeyService.verify_key",
        staticmethod(lambda db, key: None),
    )

    response = middleware_client.get(
        "/protected",
        headers={"Authorization": "Bearer invalidkey123"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"


def test_valid_api_key_injects_state_and_headers(
    middleware_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_api_key = SimpleNamespace(id="key_123")
    fake_user = SimpleNamespace(id="user_123")
    fake_user.is_admin = False
    fake_org = SimpleNamespace(id="org_123", credits_balance=2500)

    monkeypatch.setattr(
        "app.shared.core.auth_middleware.APIKeyService.verify_key",
        staticmethod(lambda db, key: (fake_api_key, fake_user, fake_org)),
    )

    response = middleware_client.get(
        "/protected",
        headers={"Authorization": "Bearer abc123"},
    )
    assert response.status_code == 200
    assert response.json() == {"user_id": "user_123", "org_id": "org_123"}
    assert response.headers["X-Organization-Id"] == "org_123"
    assert response.headers["X-Credits-Balance"] == "2500"


def test_valid_auth_on_post_endpoint(
    middleware_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST to a protected endpoint with valid auth works."""
    fake_api_key = SimpleNamespace(id="key_456")
    fake_user = SimpleNamespace(id="user_456")
    fake_org = SimpleNamespace(id="org_456", credits_balance=100)

    monkeypatch.setattr(
        "app.shared.core.auth_middleware.APIKeyService.verify_key",
        staticmethod(lambda db, key: (fake_api_key, fake_user, fake_org)),
    )

    response = middleware_client.post(
        "/api/v2/solve",
        headers={"Authorization": "Bearer validkey"},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == "user_456"
    assert response.headers["X-Organization-Id"] == "org_456"


def test_operational_error_returns_503(
    middleware_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.shared.core.auth_middleware.APIKeyService.verify_key",
        staticmethod(
            lambda db, key: (_ for _ in ()).throw(
                OperationalError("stmt", {}, Exception("db locked"))
            )
        ),
    )

    response = middleware_client.get(
        "/protected",
        headers={"Authorization": "Bearer abc123"},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "service_unavailable"


def test_unexpected_error_returns_500(
    middleware_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.shared.core.auth_middleware.APIKeyService.verify_key",
        staticmethod(lambda db, key: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    response = middleware_client.get(
        "/protected",
        headers={"Authorization": "Bearer abc123"},
    )
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "internal_error"


# CONTRACT-TEST: unauthenticated-write-rejected-before-handler
#   Every unauthenticated WRITE (POST/PUT/PATCH/DELETE) to a protected (non-
#   PUBLIC_PATHS) endpoint MUST be rejected with 401 by ASGIAuthMiddleware
#   BEFORE the route handler runs. This is the categorical guard behind the ~53
#   "401 missing on non-financial WRITE" rejection-matrix LOW cells (Phase 12.4
#   deferred): the disposition is owned by the middleware, not per-endpoint, so
#   one contract test covers the class instead of 53 per-route duplicates.
class TestUnauthenticatedWriteRejectedByMiddleware:
    """The middleware short-circuits unauthenticated WRITEs with 401 pre-handler."""

    # Representative protected WRITE route shapes (none in PUBLIC_PATHS):
    #   - flat collection POST/PUT/PATCH/DELETE
    #   - nested path-param resource
    #   - admin-scoped resource
    _ROUTES = ["/api/v2/keys", "/api/v2/organizations/org_x/members", "/api/v2/admin/settings"]
    _METHODS = ["POST", "PUT", "PATCH", "DELETE"]

    @staticmethod
    def _build_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, bool]]:
        """App whose WRITE handlers flip a sentinel iff they execute.

        If the middleware lets an unauthenticated request through, the handler
        sets ``reached[...]=True`` and we'd see it — proving the 401 came from
        the handler/route layer, not the middleware. The contract requires the
        sentinel stays False (handler never runs).
        """
        monkeypatch.setattr(
            "app.shared.core.auth_middleware.SessionLocal",
            lambda: DummySession(),
        )
        reached: dict[str, bool] = {}
        app = FastAPI(docs_url=None, redoc_url=None)

        def _make(route: str, method: str):
            async def handler() -> dict[str, bool]:
                reached[f"{method} {route}"] = True
                return {"ok": True}

            app.add_api_route(route, handler, methods=[method])

        for route in TestUnauthenticatedWriteRejectedByMiddleware._ROUTES:
            for method in TestUnauthenticatedWriteRejectedByMiddleware._METHODS:
                _make(route, method)

        app.add_middleware(ASGIAuthMiddleware)
        return TestClient(app), reached

    @pytest.mark.parametrize("method", _METHODS)
    @pytest.mark.parametrize("route", _ROUTES)
    def test_unauth_write_returns_401_before_handler(
        self, monkeypatch: pytest.MonkeyPatch, method: str, route: str
    ) -> None:
        client, reached = self._build_client(monkeypatch)

        response = client.request(method, route)

        assert response.status_code == 401, (
            f"{method} {route} without auth must be 401, got {response.status_code}"
        )
        assert response.json()["error"] == "unauthorized"
        # The handler must NOT have run — the middleware rejected pre-handler.
        assert reached.get(f"{method} {route}") is not True, (
            f"handler for {method} {route} executed despite missing auth — "
            "the 401 did not originate from the auth middleware"
        )

    def test_unauth_write_with_malformed_bearer_also_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A garbage Authorization header is treated the same as none: 401,
        no handler. Guards against a mutant that only checks header presence."""
        client, reached = self._build_client(monkeypatch)
        # An unrecognized key resolves to no principal (verify_key -> None),
        # exactly as the real service does for a bad key.
        monkeypatch.setattr(
            "app.shared.core.auth_middleware.APIKeyService.verify_key",
            staticmethod(lambda db, key: None),
        )

        response = client.request(
            "POST", "/api/v2/keys", headers={"Authorization": "Bearer not-a-real-key"}
        )

        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
        assert reached.get("POST /api/v2/keys") is not True


def test_options_request_passes_through(middleware_client: TestClient) -> None:
    """OPTIONS requests (CORS preflight) should pass through without auth.

    Either the inner app responds (200), or it returns 405 Method Not Allowed
    because /protected is a GET-only route. In neither case should auth run.
    """
    response = middleware_client.options("/protected")
    assert response.status_code in (200, 405)
    # No auth error payload should be present — if auth had run, the middleware
    # would have returned {"error": "unauthorized"}.
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        assert body.get("error") not in ("unauthorized", "service_unavailable", "internal_error")


# CONTRACT-TEST: trusted-internal-traffic-exempt-from-public-rate-limit
#   SSR / service-to-service traffic (no proxy header + private source IP) must
#   bypass the anonymous per-IP public rate limit; external clients (which always
#   arrive via Caddy with an X-Forwarded-For) must still be checked. Without this
#   all SSR renders share one 60/min bucket across every visitor → 429 → SSR 500.
class TestPublicRateLimitInternalExemption:
    """The per-IP public rate limit is applied to external clients, skipped for
    trusted internal traffic. We spy on check_rate_limit to assert *whether it
    runs*, which is exact and independent of the test-mode bypass."""

    @staticmethod
    def _build(
        monkeypatch: pytest.MonkeyPatch, client_addr: tuple[str, int]
    ) -> tuple[TestClient, list[str]]:
        monkeypatch.setattr(
            "app.shared.core.auth_middleware.SessionLocal",
            lambda: DummySession(),
        )
        calls: list[str] = []

        def _spy(key: str, **_kwargs: object) -> tuple[bool, None]:
            calls.append(key)
            return True, None

        monkeypatch.setattr("app.shared.core.auth_middleware.check_rate_limit", _spy)

        app = FastAPI(docs_url=None, redoc_url=None)

        @app.get("/api/v2/health")
        async def health() -> dict[str, bool]:
            return {"ok": True}

        app.add_middleware(ASGIAuthMiddleware)
        # Starlette TestClient lets us set the ASGI scope's client address.
        return TestClient(app, client=client_addr), calls

    def test_external_client_is_rate_limit_checked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrives via Caddy → has X-Forwarded-For → external → checked.
        client, calls = self._build(monkeypatch, ("172.18.0.9", 1234))
        resp = client.get("/api/v2/health", headers={"X-Forwarded-For": "203.0.113.7"})
        assert resp.status_code == 200
        assert calls == ["public_ip:203.0.113.7"]

    def test_internal_ssr_traffic_is_exempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Frontend SSR: direct on the Docker network, private IP, no XFF → exempt.
        client, calls = self._build(monkeypatch, ("172.18.0.9", 1234))
        resp = client.get("/api/v2/health")
        assert resp.status_code == 200
        assert calls == [], "internal SSR traffic must not hit the per-IP rate limit"

    def test_public_ip_without_proxy_header_is_still_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A public source IP with no XFF is not internal — must stay checked.
        client, calls = self._build(monkeypatch, ("8.8.8.8", 1234))
        resp = client.get("/api/v2/health")
        assert resp.status_code == 200
        assert calls == ["public_ip:8.8.8.8"]
