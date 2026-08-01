"""Prometheus collector for the SQLAlchemy connection pool (D-25).

Exposes on the existing /metrics endpoint:

- ``jaot_db_pool_size``         — configured pool size (steady-state connections).
- ``jaot_db_pool_checked_out``  — connections currently handed to a request.
- ``jaot_db_pool_available``    — idle connections ready in the pool.
- ``jaot_db_pool_overflow``     — connections opened beyond ``pool_size``.
- ``jaot_db_pool_overflow_max`` — how many overflow connections are allowed.
- ``jaot_db_pool_capacity``     — ``pool_size + max_overflow``, the ceiling a
  single process can hold.

Why this exists: admission control is wider than the pool. Endpoints are
synchronous by design (ADR-009), so each runs in the AnyIO threadpool, and in
production four worker processes each admit far more concurrent work than their
ten connections can serve. When that ratio bites, the symptom is a request
waiting out ``pool_timeout`` and then 500ing — and until now ``engine.pool``
reached no metric at all, so the failure was invisible right up to the error.

``checked_out`` approaching ``capacity`` is the leading indicator; alert on that
rather than on the 500s it eventually produces.

A custom collector (rather than plain Gauges) reads the pool at scrape time:
``QueuePool`` already tracks these counters in memory, so the read is cheap and
needs no background updater. The collector NEVER raises — an exception inside
``collect()`` breaks the entire /metrics response for every other metric.

**Read these gauges as a sample, not a total.** Production runs ``WORKERS=4``
behind one port, each process with its own pool, and Prometheus scrapes that
port — so every scrape reports whichever worker answered it, not the sum across
workers. A single high sample therefore means "at least one worker is under
pressure", which is exactly the condition worth alerting on: workers are
independent, so one saturated worker 500s while the other three sit idle.
Sustained pressure shows up reliably (a 5m window is ~20 scrapes), but do not
read an individual value as fleet-wide utilisation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from prometheus_client.core import GaugeMetricFamily

from app.shared.core.prometheus_metrics import register_collector_once

logger = logging.getLogger(__name__)


class DBPoolCollector:
    """Scrape-time collector for the jaot_db_pool_* gauges."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        stats = self._read_pool()
        if stats is None:
            return

        for name, value, doc in stats:
            gauge = GaugeMetricFamily(name, doc)
            gauge.add_metric([], value)
            yield gauge

    def _read_pool(self) -> list[tuple[str, float, str]] | None:
        try:
            # Local import keeps this module importable without the app's DB
            # stack, mirroring llm_budget_metrics.
            from app.shared.db.session import engine

            pool = engine.pool

            # QueuePool exposes these; other pool classes (NullPool in some
            # test paths) do not. Missing attributes mean "nothing to report",
            # not an error worth breaking /metrics over.
            size = pool.size()
            checked_out = pool.checkedout()
            available = pool.checkedin()
            overflow = pool.overflow()
            max_overflow = pool._max_overflow
        except Exception as exc:  # noqa: BLE001 — /metrics must never 500 on this
            logger.warning("DB pool collector read failed: %s", exc)
            return None

        # overflow() is negative before the pool has grown past its steady size;
        # report the meaningful floor of zero.
        overflow = max(0, overflow)

        return [
            (
                "jaot_db_pool_size",
                float(size),
                "Configured SQLAlchemy pool size (steady-state connections per process).",
            ),
            (
                "jaot_db_pool_checked_out",
                float(checked_out),
                "Connections currently checked out by in-flight work. Approaching "
                "jaot_db_pool_capacity is the leading indicator of pool exhaustion.",
            ),
            (
                "jaot_db_pool_available",
                float(available),
                "Idle connections currently available in the pool.",
            ),
            (
                "jaot_db_pool_overflow",
                float(overflow),
                "Connections opened beyond pool_size (0 until the pool grows).",
            ),
            (
                "jaot_db_pool_overflow_max",
                float(max_overflow),
                "Maximum overflow connections allowed beyond pool_size.",
            ),
            (
                "jaot_db_pool_capacity",
                float(size + max_overflow),
                "pool_size + max_overflow — the connection ceiling for this process.",
            ),
        ]


def register_db_pool_collector() -> None:
    """Register the collector on the default registry, idempotently."""
    register_collector_once(DBPoolCollector())


__all__ = ["DBPoolCollector", "register_db_pool_collector"]
