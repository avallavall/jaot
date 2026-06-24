"""Hexaly worker health probe — domain-friendly module.

Phase 7.4 / FIX-CI: extracted from ``app/api/v2/health.py`` so solver-domain
services (``auto_router``, ``availability_gate``) can probe Celery worker
health without transitively pulling in ``pyscipopt`` via the api/v2/health
module. Keeps the ``solver-services-must-not-import-pyscipopt`` import-linter
contract intact while preserving identical caching/lock semantics.

The TTL cache and single-flight lock live HERE — not in callers — because
both ``/api/v2/solvers/available`` and ``/api/v2/health/status`` and the
solver auto-router share the cache transparently. Moving the cache into a
caller would force every caller to maintain its own.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)

# Cache the Hexaly-worker probe for a short window. celery_app.control.inspect()
# broadcasts to every worker and blocks for the full timeout; without a cache
# every /health/status hit pays that cost. 15s TTL is safe because the fleet
# state does not change on sub-second scales.
_HEXALY_PROBE_CACHE_SECONDS = 15.0
_HEXALY_PROBE_TIMEOUT_SECONDS = 0.5
_hexaly_probe_cache: tuple[float, bool, str | None] | None = None
_hexaly_probe_lock = Lock()


def _probe_hexaly_worker() -> tuple[bool, str | None]:
    """Check that a Hexaly worker is bound to the ``solve_hexaly`` queue.

    Returns ``(queue_ok, message)``. ``queue_ok`` is True iff at least one
    worker reports the ``solve_hexaly`` queue via ``inspect().active_queues()``.
    Generic ``ping()`` is insufficient: any SCIP / HiGHS worker would answer
    and falsely flip the status to healthy.

    Uses a short (500 ms) broker timeout + a process-local TTL cache so a
    flapping broker cannot cascade into 2-second uvicorn stalls. All broker
    failures are swallowed into a ``degraded`` message — infrastructure
    probes must never raise from this layer.

    Uses double-checked locking: the fast path reads the cache without taking
    the lock (CPython tuple assignment is atomic under the GIL), so warm
    readers do not serialize on ``_hexaly_probe_lock``. The lock is only
    acquired when the cache is empty or expired, and a re-check inside the
    lock prevents the cache-stampede hole where N concurrent requests all
    see "cache empty" and all fire their own broker broadcast.
    """
    global _hexaly_probe_cache

    # Fast path: lock-free cache read. Tuple binding is atomic under the GIL;
    # the worst case is reading a value that just expired, which the lock-
    # protected slow path will refresh on the next call.
    cached = _hexaly_probe_cache
    if cached is not None and (time.monotonic() - cached[0]) < _HEXALY_PROBE_CACHE_SECONDS:
        return (cached[1], cached[2])

    with _hexaly_probe_lock:
        # Re-check inside the lock — another thread may have refreshed the
        # cache while we were waiting. Stops a thundering herd of broker
        # broadcasts when the cache expires under load.
        cached = _hexaly_probe_cache
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < _HEXALY_PROBE_CACHE_SECONDS:
            return (cached[1], cached[2])

        queue_ok = False
        message: str | None = None
        try:
            from app.domains.solver.queue_routing import SOLVER_QUEUE_MAP
            from app.shared.core.celery_app import celery_app

            hexaly_queue_name = SOLVER_QUEUE_MAP["hexaly"]
            inspector = celery_app.control.inspect(timeout=_HEXALY_PROBE_TIMEOUT_SECONDS)
            queues_by_worker = inspector.active_queues() or {}
            queue_ok = any(
                any(q.get("name") == hexaly_queue_name for q in (queues or []))
                for queues in queues_by_worker.values()
            )
            if not queue_ok:
                message = f"No worker bound to {hexaly_queue_name} queue"
        except Exception as exc:  # noqa: BLE001 — infra probe must degrade, never raise
            message = f"Hexaly worker probe failed: {str(exc)[:100]}"

        _hexaly_probe_cache = (now, queue_ok, message)
        return (queue_ok, message)
