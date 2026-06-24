"""Tests for CORS configuration restrictions.

These are pure unit tests that do NOT require a database connection.
The autouse fixtures from conftest.py are overridden to avoid DB dependency.
"""

import pytest
from starlette.testclient import TestClient

from app.main import create_app


# Override autouse fixtures from conftest.py -- these tests need no database.
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
def client():
    app = create_app()
    return TestClient(app)


def test_cors_allows_configured_methods(client):
    """Preflight should list explicit methods, not wildcard."""
    resp = client.options(
        "/api/v2/health",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "POST",
        },
    )
    allowed = resp.headers.get("access-control-allow-methods", "")
    assert "GET" in allowed
    assert "POST" in allowed
    assert "PUT" in allowed
    assert "DELETE" in allowed
    assert "PATCH" in allowed


def test_cors_allows_configured_headers(client):
    """Preflight should list explicit headers, not wildcard."""
    resp = client.options(
        "/api/v2/health",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "GET",
            "access-control-request-headers": "Authorization, Content-Type",
        },
    )
    allowed = resp.headers.get("access-control-allow-headers", "")
    assert "authorization" in allowed.lower()
    assert "content-type" in allowed.lower()


def test_cors_rejects_unknown_origin(client):
    """Requests from unknown origins should not get CORS headers."""
    resp = client.options(
        "/api/v2/health",
        headers={
            "origin": "http://evil.example.com",
            "access-control-request-method": "GET",
        },
    )
    # Should not have access-control-allow-origin for unknown origin
    allow_origin = resp.headers.get("access-control-allow-origin")
    assert allow_origin is None or "evil.example.com" not in allow_origin
