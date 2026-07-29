"""Time limits for a solve, with the platform's configured defaults filled in.

The derivation itself lives in ``app/domains/solver/time_limits.py`` and takes
plain numbers: a solver has no reason to know that this installation keeps its
defaults in a ``platform_settings`` table, and a solver shipped as its own
package could not read one anyway.

This is where that knowledge belongs — the layer that has the session and the
settings service. Two thin readers, so the five call sites do not each repeat
the lookup (D-16).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.solver.time_limits import (
    compute_celery_time_limits as domain_compute_celery_time_limits,
    resolve_solver_time_limit as domain_resolve_solver_time_limit,
)
from app.services.platform_settings_service import PlatformSettingsService as PSS


def resolve_solver_time_limit(
    db: Session,
    solver_name: str | None,
    requested_seconds: float | None,
) -> float | None:
    """The time limit a solve should carry, falling back to the configured default.

    Only a metaheuristic solver needs the fallback — see the domain function for
    why — so the setting is read only when one is in play.
    """
    if requested_seconds is not None and requested_seconds > 0:
        return requested_seconds
    if (solver_name or "").lower() != "hexaly":
        return requested_seconds
    return domain_resolve_solver_time_limit(
        solver_name,
        requested_seconds,
        PSS.get_int(db, "hexaly_default_time_limit_seconds"),
    )


def compute_celery_time_limits(
    db: Session,
    time_limit_seconds: float | None,
) -> tuple[int, int]:
    """``(soft, hard)`` worker limits for a solve task, in whole seconds."""
    return domain_compute_celery_time_limits(
        time_limit_seconds,
        PSS.get_int(db, "SOLVER_DEFAULT_TIMEOUT"),
    )
