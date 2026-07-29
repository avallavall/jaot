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

# Margin on top of the solver's own time limit before the soft kill fires.
# Covers problem parsing, model build, warm-start loading, and result
# serialization that happen around the actual solve inside the task.
SOFT_MARGIN_SECONDS = 60

# Extra headroom between the soft and hard limits so the
# SoftTimeLimitExceeded handler (refund + execution row update) can finish
# before the worker child is SIGKILLed.
HARD_GRACE_SECONDS = 30


def resolve_solver_time_limit(
    solver_name: str | None,
    requested_seconds: float | None,
    hexaly_default_seconds: float,
) -> float | None:
    """Return the time limit the solve should carry, in seconds.

    An absent limit means "run to proven optimality" — legitimate for the
    exact solvers, whose search terminates on its own. Hexaly is
    metaheuristic: it improves an incumbent until something stops it, so an
    absent limit there is not "no limit", it is "never returns". Those
    requests get ``hexaly_default_time_limit_seconds``.

    An explicit request always wins, including for Hexaly — the setting is
    the floor under requests that name no limit, not a cap on the ones that do.

    Args:
        db: Database session (used only for the platform-setting lookup).
        solver_name: The EFFECTIVE solver, after auto-routing. Passing the
            requested name instead would miss every ``auto`` request the
            router sends to Hexaly.
        requested_seconds: The per-request limit, if the caller set one.

    Returns:
        The effective limit, or ``None`` to leave the solve unbounded.
    """
    if requested_seconds is not None and requested_seconds > 0:
        return requested_seconds
    if (solver_name or "").lower() != "hexaly":
        return requested_seconds

    return float(hexaly_default_seconds)


def compute_celery_time_limits(
    time_limit_seconds: float | None,
    default_timeout_seconds: float,
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
    if time_limit_seconds is not None and time_limit_seconds > 0:
        base = float(time_limit_seconds)
    else:
        base = float(default_timeout_seconds)

    soft = int(base) + SOFT_MARGIN_SECONDS
    return soft, soft + HARD_GRACE_SECONDS


__all__ = [
    "HARD_GRACE_SECONDS",
    "SOFT_MARGIN_SECONDS",
    "compute_celery_time_limits",
    "resolve_solver_time_limit",
]
