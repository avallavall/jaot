"""Tests for security response headers middleware.

These are pure unit tests that do NOT require a database connection.
The autouse fixtures from conftest.py are overridden to avoid DB dependency.
"""

import re

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


def test_x_content_type_options(client):
    resp = client.get("/api/v2/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"


def test_x_frame_options(client):
    resp = client.get("/api/v2/health")
    assert resp.headers.get("x-frame-options") == "DENY"


def test_referrer_policy(client):
    resp = client.get("/api/v2/health")
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_hsts(client):
    resp = client.get("/api/v2/health")
    hsts = resp.headers.get("strict-transport-security")
    assert hsts is not None
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" not in hsts


def test_csp_contains_required_directives(client):
    resp = client.get("/api/v2/health")
    csp = resp.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "nonce-" in csp
    assert "frame-ancestors 'none'" in csp
    # M-1 fix: style-src now includes a per-request nonce
    assert re.search(r"style-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'unsafe-inline'", csp), (
        f"Expected style-src with nonce in CSP, got: {csp}"
    )


def test_csp_nonce_unique_per_request(client):
    resp1 = client.get("/api/v2/health")
    resp2 = client.get("/api/v2/health")
    csp1 = resp1.headers.get("content-security-policy")
    csp2 = resp2.headers.get("content-security-policy")
    # Extract nonce values
    nonces1 = re.findall(r"nonce-([A-Za-z0-9+/=]+)", csp1)
    nonces2 = re.findall(r"nonce-([A-Za-z0-9+/=]+)", csp2)
    assert nonces1 and nonces2
    assert nonces1[0] != nonces2[0], "CSP nonce must be unique per request"


def test_permissions_policy(client):
    resp = client.get("/api/v2/health")
    pp = resp.headers.get("permissions-policy")
    assert pp is not None
    assert "camera=()" in pp
    assert "microphone=()" in pp
    assert "geolocation=()" in pp


def test_api_responses_are_no_store(client):
    """API responses must default to Cache-Control: no-store.

    Guards the "empty admin list" bug: without no-store, a stale empty
    response can be served from the browser/CDN cache and the real request
    never reaches the server.
    """
    resp = client.get("/api/v2/health")
    assert resp.headers.get("cache-control") == "no-store"
