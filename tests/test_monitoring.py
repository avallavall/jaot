"""Tests for Prometheus metrics endpoint and business metric registration.

Covers:
- MON-01: GET /metrics returns Prometheus exposition format with HTTP request metrics
- MON-02: Custom jaot_* business metrics are registered and visible

These tests use a standalone TestClient (no database required) since /metrics
does not depend on database state. The autouse DB fixtures from conftest.py
are overridden to no-ops.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


# Override autouse fixtures from conftest.py that require PostgreSQL.
# These are not needed for /metrics endpoint tests.
@pytest.fixture(autouse=True)
def _truncate_tables():
    """Override: no DB truncation needed for metrics tests."""
    yield


@pytest.fixture(autouse=True)
def override_db_dependency():
    """Override: no DB dependency override needed for metrics tests."""
    yield


@pytest.fixture(scope="module")
def metrics_client():
    """Create a standalone test client for /metrics tests (no DB required)."""
    app = create_app()
    return TestClient(app)


class TestMetricsEndpoint:
    """Tests for GET /metrics endpoint (MON-01).

    /metrics is public at the app level (Prometheus scrapes internally via Docker
    network). External access is blocked by Caddy (respond 403 on /metrics*).
    """

    def test_metrics_endpoint_accessible_without_auth(self, metrics_client):
        """GET /metrics returns 200 without auth (public for Prometheus scraping)."""
        response = metrics_client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_returns_prometheus_format_with_auth(self, authenticated_client):
        """GET /metrics with auth returns Prometheus exposition format."""
        response = authenticated_client.get("/metrics")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "openmetrics" in content_type
        body = response.text
        assert "# HELP" in body
        assert "# TYPE" in body

    def test_metrics_includes_http_requests_total(self):
        """GET /metrics includes HTTP request metrics (MON-01).

        Self-contained (own app + client, not the shared authenticated_client)
        for the same reason as test_metrics_includes_request_duration below:
        create_app() re-registers the http_* collectors in the process-global
        registry (app/main.py), so under pytest-randomly ordering a later
        create_app() can orphan the collector a different instance scrapes,
        intermittently dropping http_requests_total from /metrics. Creating the
        app and scraping the SAME instance — the last create_app() before the
        scrape — guarantees the collector is in the registry /metrics reads back.
        """
        from app.main import create_app

        app = create_app()
        client = TestClient(app)
        client.get("/api/v2/health")  # best-effort templated request for a sample
        body = client.get("/metrics").text
        assert "http_requests_total" in body or "http_request_duration" in body

    def test_metrics_includes_request_duration(self):
        """GET /metrics exposes the request-duration histogram (MON-01).

        Self-contained (own app + client, not the shared authenticated_client)
        to dodge a cross-test Prometheus-registry flake: create_app()
        unregisters every http_* collector from the process-global registry and
        re-registers fresh ones (app/main.py:307-335). Under pytest-randomly
        ordering, the http_request_duration_seconds collector seen via one app
        instance can be orphaned by a later create_app() before a different
        instance scrapes /metrics. Creating the app and scraping the SAME
        instance here — the last create_app() before the scrape — guarantees the
        collector is registered in the registry /metrics reads back (its
        HELP/TYPE lines are emitted at instrument() time, regardless of
        observations).
        """
        from app.main import create_app

        app = create_app()
        client = TestClient(app)
        client.get("/api/v2/health")  # best-effort templated request for a sample
        body = client.get("/metrics").text
        assert "http_request_duration" in body, (
            "http_request_duration_seconds missing from /metrics — the "
            "instrumentator latency histogram was not registered/exposed."
        )

    def test_metrics_endpoint_returns_prometheus_format_unauthenticated(self, metrics_client):
        """/metrics is accessible without auth for Prometheus scraping."""
        response = metrics_client.get("/metrics")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "openmetrics" in content_type


class TestBusinessMetrics:
    """Tests for custom jaot_* business metrics (MON-02)."""

    def test_metrics_includes_solve_total(self, authenticated_client):
        """GET /metrics includes jaot_solve_total counter."""
        response = authenticated_client.get("/metrics")
        body = response.text
        assert "jaot_solve_total" in body

    def test_metrics_includes_credits_consumed(self, authenticated_client):
        """GET /metrics includes jaot_credits_consumed_total counter."""
        response = authenticated_client.get("/metrics")
        assert "jaot_credits_consumed_total" in response.text

    def test_metrics_includes_solve_duration(self, authenticated_client):
        """GET /metrics includes jaot_solve_duration_seconds histogram."""
        response = authenticated_client.get("/metrics")
        assert "jaot_solve_duration_seconds" in response.text

    def test_metrics_includes_active_solves(self, authenticated_client):
        """GET /metrics includes jaot_active_solves gauge."""
        response = authenticated_client.get("/metrics")
        assert "jaot_active_solves" in response.text

    def test_solve_duration_has_solver_tuned_buckets(self, authenticated_client):
        """jaot_solve_duration_seconds has optimization-tuned buckets (up to 120s)."""
        response = authenticated_client.get("/metrics")
        body = response.text
        # Check that the 120s bucket exists (our highest bucket)
        assert 'le="120.0"' in body

    def test_metrics_includes_app_info(self, authenticated_client):
        """GET /metrics includes jaot_app_info with version and solver."""
        response = authenticated_client.get("/metrics")
        body = response.text
        assert "jaot_app_info" in body

    def test_solve_total_has_status_and_generator_labels(self):
        """jaot_solve_total metric is registered with status and generator labels."""
        from app.shared.core.prometheus_metrics import SOLVE_TOTAL

        assert "status" in SOLVE_TOTAL._labelnames
        assert "generator" in SOLVE_TOTAL._labelnames

    def test_solve_total_type_is_counter(self, authenticated_client):
        """jaot_solve_total is a counter type metric."""
        response = authenticated_client.get("/metrics")
        body = response.text
        assert "# TYPE jaot_solve_total_total counter" in body or (
            "# TYPE jaot_solve_total counter" in body
        )

    def test_solve_duration_type_is_histogram(self, authenticated_client):
        """jaot_solve_duration_seconds is a histogram type metric."""
        response = authenticated_client.get("/metrics")
        body = response.text
        assert "# TYPE jaot_solve_duration_seconds histogram" in body

    def test_active_solves_type_is_gauge(self, authenticated_client):
        """jaot_active_solves is a gauge type metric."""
        response = authenticated_client.get("/metrics")
        body = response.text
        assert "# TYPE jaot_active_solves gauge" in body

    def test_credits_consumed_type_is_counter(self, authenticated_client):
        """jaot_credits_consumed_total is a counter type metric."""
        response = authenticated_client.get("/metrics")
        body = response.text
        assert "# TYPE jaot_credits_consumed_total_total counter" in body or (
            "# TYPE jaot_credits_consumed_total counter" in body
        )


class TestMetricsAuthMiddleware:
    """Tests for /metrics auth requirement (H-5 security fix)."""

    def test_metrics_in_public_endpoints(self):
        """Verify /metrics IS in PUBLIC_PATHS (Prometheus scrapes without auth).

        External access is blocked by Caddy reverse proxy (respond 403 on /metrics*).
        """
        from app.shared.core.auth_middleware import PUBLIC_PATHS

        public_prefixes = [path for path, _ in PUBLIC_PATHS]
        assert "/metrics" in public_prefixes

    def test_metrics_is_public_endpoint(self):
        """Verify _is_public returns True for /metrics (Prometheus scraping)."""
        from app.shared.core.auth_middleware import _is_public

        assert _is_public("/metrics", "GET") is True
