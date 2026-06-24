"""Pre-debit availability gate for direct-Hexaly solver selection.

Phase 7.4 / D-11 — when a customer explicitly selects ``solver_name="hexaly"``
on any solve entry point AND the Hexaly worker is unavailable, return 503
with the canonical error body BEFORE any credit operation. This avoids the
"deduct -> solve fails -> refund" CreditTransaction churn that the
unprotected paths used to produce.

Extracted from inline blocks in ``app/api/v2/solve.py`` so all four solve
entry points share one truth (WR-04 fix):

- ``/api/v2/solve``                              (sync)
- ``/api/v2/solve/async``                        (async)
- ``/api/v2/import``                             (file_io)
- ``/api/v2/solve/templates/{template_id}/solve``(templates)

The helper relies on ``app.domains.solver.services.worker_health._probe_hexaly_worker``
(15s TTL cache + Celery ``inspect().active_queues()`` filtered for ``solve_hexaly``).
"""

from __future__ import annotations

from fastapi import HTTPException

from app.domains.solver.adapters.base import HEXALY_SOLVER_NAME

# Canonical 503 message — used by all four solve entry points so the
# frontend sees a stable string regardless of which route the customer hit.
_HEXALY_UNAVAILABLE_MESSAGE = "Hexaly is temporarily in maintenance. Try SCIP/HiGHS or retry later."


def ensure_hexaly_worker_or_503(effective_solver_name: str | None) -> None:
    """Raise 503 when ``effective_solver_name`` is ``hexaly`` and no worker is
    bound to the ``solve_hexaly`` Celery queue.

    No-op for any other solver name (including ``None``, ``"scip"``,
    ``"highs"``, ``"auto"``). The auto-router handles ``"auto"`` separately
    via ``hexaly_unavailable_fallback`` (D-11) — by the time this gate fires
    the solver name has already been resolved post-routing.

    Honors the D-11 error contract:
        503 {"error": "solver_unavailable", "solver": "hexaly", "message": ...}

    Args:
        effective_solver_name: Resolved solver name (post auto-router for
            "auto" requests, or the raw user-selected name for direct
            requests). ``None`` means "use default" — never Hexaly.

    Raises:
        HTTPException(503): When the user selected Hexaly directly and no
            Hexaly worker is healthy.
    """
    if effective_solver_name != HEXALY_SOLVER_NAME:
        return

    # Lazy import from the domain-friendly module so the gate module stays
    # cheap and the solver-services import-linter contract holds (worker_health
    # does not transitively reach pyscipopt).
    from app.domains.solver.services.worker_health import _probe_hexaly_worker  # noqa: PLC0415

    healthy, _msg = _probe_hexaly_worker()
    if not healthy:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "solver_unavailable",
                "solver": HEXALY_SOLVER_NAME,
                "message": _HEXALY_UNAVAILABLE_MESSAGE,
            },
        )


__all__ = ["ensure_hexaly_worker_or_503"]
