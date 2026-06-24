"""Integration tests for GET /api/v2/health/status — Phase 7.1 Plan 03.

Covers HIGH-02 (per-queue Hexaly health discrimination):

    Test 1: No Hexaly worker running → solver_worker_hexaly component is degraded
            with a message that names the solve_hexaly queue explicitly.
    Test 2: Hexaly worker bound to solve_hexaly → solver_worker_hexaly is healthy.
    Test 3: Cache respected — two rapid calls hit the broker probe exactly once.

All tests clear the process-global _hexaly_probe_cache before running.
"""

from __future__ import annotations

import pytest

# Autouse fixture: clear probe cache before every test


@pytest.fixture(autouse=True)
def _clear_hexaly_probe_cache(monkeypatch):
    """/health cache is process-global; wipe before every test.

    Phase 7.4 / FIX-CI: cache moved to ``app.domains.solver.services.worker_health``
    so solver-services don't transitively import pyscipopt via api.v2.health.
    """
    import app.domains.solver.services.worker_health as worker_health_mod

    monkeypatch.setattr(worker_health_mod, "_hexaly_probe_cache", None)
    yield


def _make_inspector(queues_by_worker: dict) -> object:
    """Return a fake celery_app that reports queues_by_worker via active_queues()."""

    class _FakeInspector:
        def active_queues(self):  # noqa: ANN202
            return queues_by_worker

    class _FakeControl:
        def inspect(self, timeout):  # noqa: ANN001,ANN202
            return _FakeInspector()

    class _FakeApp:
        control = _FakeControl()

    return _FakeApp()


# Test 1 — degraded when no Hexaly worker


def test_hexaly_component_degraded_when_no_worker(authenticated_client, monkeypatch):
    """HIGH-02 regression lock — queue-name filter, not generic ping.

    A worker bound only to solve_scip must NOT make solver_worker_hexaly healthy.
    """
    import app.api.v2.health as health_mod

    # Only a SCIP worker is present — no hexaly queue.
    fake_app = _make_inspector({"worker-scip@host": [{"name": "solve_scip"}]})
    monkeypatch.setattr(
        "app.api.v2.health.celery_app",
        fake_app,
        raising=False,
    )
    # Ensure the health module's own import path resolves to our fake.
    import app.shared.core.celery_app as celery_mod

    monkeypatch.setattr(celery_mod, "celery_app", fake_app)

    # Force sdk_importable to True so we actually exercise the probe path.
    monkeypatch.setattr(
        "app.domains.solver.adapters.hexaly_availability.hexaly_available",
        lambda: True,
    )
    # Also patch via health module's import namespace.
    monkeypatch.setattr(
        health_mod,
        "_probe_hexaly_worker",
        lambda: _probe_with_fake(fake_app),
        raising=False,
    )

    resp = authenticated_client.get("/api/v2/health/status")
    assert resp.status_code == 200
    components = {c["name"]: c for c in resp.json()["components"]}
    assert "solver_worker_hexaly" in components
    assert components["solver_worker_hexaly"]["status"] == "degraded"
    assert "solve_hexaly" in (components["solver_worker_hexaly"].get("message") or "")


def _probe_with_fake(fake_app):  # noqa: ANN001,ANN202
    """Run the real _probe_hexaly_worker body but with a patched celery_app."""
    import time

    import app.domains.solver.services.worker_health as worker_health_mod
    from app.domains.solver.queue_routing import SOLVER_QUEUE_MAP

    hexaly_queue_name = SOLVER_QUEUE_MAP["hexaly"]
    try:
        inspector = fake_app.control.inspect(
            timeout=worker_health_mod._HEXALY_PROBE_TIMEOUT_SECONDS
        )
        queues_by_worker = inspector.active_queues() or {}
        queue_ok = any(
            any(q.get("name") == hexaly_queue_name for q in (queues or []))
            for queues in queues_by_worker.values()
        )
        if not queue_ok:
            message: str | None = f"No worker bound to {hexaly_queue_name} queue"
    except Exception as exc:  # noqa: BLE001
        queue_ok = False
        message = f"Hexaly worker probe failed: {str(exc)[:100]}"

    worker_health_mod._hexaly_probe_cache = (
        time.monotonic(),
        queue_ok,
        message if not queue_ok else None,
    )
    return (queue_ok, message if not queue_ok else None)


# Test 2 — healthy when Hexaly worker reports solve_hexaly queue


def test_hexaly_component_healthy_when_worker_reports_queue(authenticated_client, monkeypatch):
    """A worker bound to solve_hexaly must flip solver_worker_hexaly to healthy."""
    import app.api.v2.health as health_mod
    import app.shared.core.celery_app as celery_mod

    fake_app = _make_inspector({"worker-hexaly@host": [{"name": "solve_hexaly"}]})
    monkeypatch.setattr(celery_mod, "celery_app", fake_app)

    monkeypatch.setattr(
        "app.domains.solver.adapters.hexaly_availability.hexaly_available",
        lambda: True,
    )
    monkeypatch.setattr(
        health_mod,
        "_probe_hexaly_worker",
        lambda: _probe_with_fake(fake_app),
        raising=False,
    )

    resp = authenticated_client.get("/api/v2/health/status")
    assert resp.status_code == 200
    components = {c["name"]: c for c in resp.json()["components"]}
    assert "solver_worker_hexaly" in components
    assert components["solver_worker_hexaly"]["status"] == "healthy"


# Test 3 — TTL cache is respected (single-flight under rapid probes)


def test_hexaly_probe_cache_respected(authenticated_client, monkeypatch):
    """Two rapid /health/status calls must invoke the broker exactly once (TTL cache).

    Patches the *innermost* level: the fake inspector's active_queues() is a
    counter, so we verify the broker broadcast only fires once across two
    /health/status calls that both arrive within the 15s TTL window.
    """
    import app.domains.solver.services.worker_health as worker_health_mod
    import app.shared.core.celery_app as celery_mod

    call_count = {"n": 0}

    class _CountingInspector:
        def active_queues(self):  # noqa: ANN202
            call_count["n"] += 1
            return {}  # no hexaly worker → degraded

    class _CountingControl:
        def inspect(self, timeout):  # noqa: ANN001,ANN202
            return _CountingInspector()

    class _CountingApp:
        control = _CountingControl()

    monkeypatch.setattr(celery_mod, "celery_app", _CountingApp())
    monkeypatch.setattr(
        "app.domains.solver.adapters.hexaly_availability.hexaly_available",
        lambda: True,
    )
    # Clear the cache so the first request always triggers a probe.
    monkeypatch.setattr(worker_health_mod, "_hexaly_probe_cache", None)

    # First hit — broker probe fires once.
    resp1 = authenticated_client.get("/api/v2/health/status")
    assert resp1.status_code == 200

    # Second hit (well within 15s TTL) — broker broadcast must NOT fire again.
    resp2 = authenticated_client.get("/api/v2/health/status")
    assert resp2.status_code == 200

    # active_queues() called exactly once across two /health/status requests.
    assert call_count["n"] == 1, (
        f"Expected broker probe exactly once (TTL cache hit), got {call_count['n']}"
    )
