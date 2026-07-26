"""The health endpoint must never block the event loop.

`GET /api/v2/health` is the most-called endpoint in the system: the container
health check polls it, and that traffic is classified as trusted internal, so it
is exempt from the public rate limit. It used to call
``psutil.cpu_percent(interval=0.1)``, which sleeps 100ms *inside* the call — and
because the handler runs on the event loop, every health check froze the whole
worker for that long (backend audit 2026-07-26, F-02 / D-10).

These tests pin the fix by asserting on how psutil is called, not by timing the
response: a latency threshold would be flaky on a loaded CI box, while the
blocking-vs-non-blocking distinction is exactly the invariant we care about.
"""

import psutil

from app.api.v2 import health as health_module


class TestHealthDoesNotBlock:
    """# CONTRACT-TEST: the health check never samples CPU with a blocking interval."""

    def test_cpu_is_read_without_a_blocking_interval(self, client, db_session, monkeypatch):
        """psutil.cpu_percent is called with interval=None (delta, no sleep)."""
        calls: list[object] = []
        real = psutil.cpu_percent

        def recording_cpu_percent(*args, **kwargs):
            # Record whichever way the interval was passed: positionally or by keyword.
            calls.append(
                kwargs["interval"] if "interval" in kwargs else (args[0] if args else None)
            )
            return real(interval=None)

        monkeypatch.setattr(health_module.psutil, "cpu_percent", recording_cpu_percent)

        resp = client.get("/api/v2/health")

        assert resp.status_code == 200
        assert calls, "the health endpoint no longer reads CPU at all"
        for interval in calls:
            assert interval is None or interval == 0, (
                f"health check sampled CPU with a blocking interval={interval!r}; "
                "that sleeps on the event loop and stalls every concurrent request"
            )

    def test_cpu_percent_is_still_reported(self, client, db_session):
        """The non-blocking read must still produce a usable number, not a null."""
        resp = client.get("/api/v2/health")

        assert resp.status_code == 200
        cpu = resp.json()["system"]["cpu_percent"]
        assert isinstance(cpu, (int, float))
        assert 0.0 <= cpu <= 100.0

    def test_repeated_calls_stay_healthy(self, client, db_session):
        """Consecutive polls behave like the container health check does."""
        for _ in range(3):
            resp = client.get("/api/v2/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
