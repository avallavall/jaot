"""Celery worker time-limit derivation for solve tasks (W15 / F-01).

Solver-internal limits (``OptimizationProblem.options.time_limit_seconds``,
e.g. SCIP ``limits/time``) stop well-behaved solves, but a C-extension hang
survives them and pins a concurrency-2 worker indefinitely. Producers
therefore pass per-task ``soft_time_limit`` / ``time_limit`` options to
``apply_async``, derived from the request's own solver time limit plus a
margin:

- **soft limit** = solver limit + :data:`SOFT_MARGIN_SECONDS` — Celery raises
  ``SoftTimeLimitExceeded`` inside the task, which flows into the existing
  except-branch (idempotent refund + ModelExecution marked failed).
- **hard limit** = soft + :data:`HARD_GRACE_SECONDS` — the worker child is
  SIGKILLed if the soft exception is swallowed by C code; Celery records
  FAILURE in the result backend and the execution reaper
  (``app/tasks/execution_reaper.py``) reconciles the DB row + refund.

``SOLVER_DEFAULT_TIMEOUT`` (platform setting, default 300s) is the fallback
base when a request carries no usable time limit.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

# Margin on top of the solver's own time limit before the soft kill fires.
# Covers problem parsing, model build, warm-start loading, and result
# serialization that happen around the actual solve inside the task.
SOFT_MARGIN_SECONDS = 60

# Extra headroom between the soft and hard limits so the
# SoftTimeLimitExceeded handler (refund + execution row update) can finish
# before the worker child is SIGKILLed.
HARD_GRACE_SECONDS = 30


def compute_celery_time_limits(
    db: Session,
    time_limit_seconds: float | None,
) -> tuple[int, int]:
    """Return ``(soft_time_limit, time_limit)`` seconds for a solve task.

    Args:
        db: Database session (used only for the ``SOLVER_DEFAULT_TIMEOUT``
            platform-setting fallback).
        time_limit_seconds: The per-request solver time limit
            (``problem.options.time_limit_seconds``). ``None`` or
            non-positive values fall back to ``SOLVER_DEFAULT_TIMEOUT``.

    Returns:
        Tuple of (soft limit, hard limit) in whole seconds, with
        ``hard = soft + HARD_GRACE_SECONDS``.
    """
    from app.services.platform_settings_service import PlatformSettingsService as PSS

    if time_limit_seconds is not None and time_limit_seconds > 0:
        base = float(time_limit_seconds)
    else:
        base = float(PSS.get_int(db, "SOLVER_DEFAULT_TIMEOUT"))

    soft = int(base) + SOFT_MARGIN_SECONDS
    return soft, soft + HARD_GRACE_SECONDS


__all__ = [
    "HARD_GRACE_SECONDS",
    "SOFT_MARGIN_SECONDS",
    "compute_celery_time_limits",
]
