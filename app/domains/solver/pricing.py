"""Credit pricing for solves (ADR-007 S3).

Pure pricing functions, extracted from ``app.api.v2.solve`` so every solve
entry point — the HTTP routes, the marketplace ``execute_model``, and the
trigger worker — can price a problem without importing the API router module
(a Celery task reaching into ``app.api`` is a layering smell this removes).

Imports only ``app.schemas`` + ``PlatformSettingsService``; no solver, no API,
no pyscipopt. ``app.api.v2.solve`` re-exports ``calculate_credits`` so existing
importers keep working unchanged.
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.schemas.optimization import OptimizationProblem, SolverOptions
from app.services.platform_settings_service import (
    MissingSettingError,
    PlatformSettingsService as PSS,
)

# The default solver time limit is free: the time bonus only charges for time
# REQUESTED BEYOND the platform default, so a problem solved with default options
# always prices at the base formula. Derived from the schema so the two can't drift.
FREE_TIME_LIMIT_SECONDS = float(SolverOptions.model_fields["time_limit_seconds"].default)


def compute_credits(
    num_variables: int,
    num_integer_binary: int,
    num_constraints: int,
    time_limit_seconds: float = FREE_TIME_LIMIT_SECONDS,
    *,
    max_credits_per_solve: int = 500,
) -> tuple[int, dict[str, float]]:
    """Compute credits with sublinear (sqrt) scaling and a per-solve cap.

    The formula uses sqrt scaling so that large enterprise problems remain
    affordable.  Small problems (<100 vars) keep near-linear pricing for
    simplicity.

    Returns:
        (total_credits, breakdown_dict)
    """
    # --- base ---
    base = 1.0

    # --- variable cost: sqrt scaling ---
    if num_variables <= 100:
        var_cost = num_variables * 0.1
    else:
        var_cost = 10.0 + math.sqrt(num_variables - 100) * 1.5

    # --- MIP penalty: sqrt of integer/binary count ---
    mip_cost = math.sqrt(num_integer_binary) * 2.0 if num_integer_binary > 0 else 0.0

    # --- constraint cost: sqrt scaling ---
    if num_constraints <= 50:
        con_cost = num_constraints * 0.05
    else:
        con_cost = 2.5 + math.sqrt(num_constraints - 50) * 0.5

    # --- time bonus: 1 credit per extra minute beyond the free default limit ---
    if time_limit_seconds > FREE_TIME_LIMIT_SECONDS:
        time_cost = math.ceil((time_limit_seconds - FREE_TIME_LIMIT_SECONDS) / 60)
    else:
        time_cost = 0.0

    raw_total = base + var_cost + mip_cost + con_cost + time_cost
    capped = min(raw_total, max_credits_per_solve)
    total = max(1, round(capped))

    breakdown = {
        "base_cost": base,
        "variable_cost": round(var_cost, 2),
        "mip_penalty": round(mip_cost, 2),
        "constraint_cost": round(con_cost, 2),
        "time_bonus": round(time_cost, 2),
        "raw_total": round(raw_total, 2),
        "cap_applied": raw_total > max_credits_per_solve,
        "max_credits_per_solve": max_credits_per_solve,
    }
    return total, breakdown


def calculate_credits(
    problem: OptimizationProblem,
    solver_name: str | None = None,
    db: Session | None = None,
) -> int:
    """Calculate credits required based on problem complexity.

    PRC-01 / D-02: when ``solver_name`` and ``db`` are both
    provided, the base credit total is multiplied by the PSS-resolved
    per-solver multiplier (``pricing.solver_multiplier.<solver_name>``,
    defaults 1.0/1.2/5.0 for scip/highs/hexaly). When omitted, returns
    base credits unchanged — used by preview/estimate endpoints
    (validate-credits, file_io estimate, template render, file_io needed)
    per D-02 spec.

    Args:
        problem: The optimization problem to price.
        solver_name: Effective solver name AFTER auto-routing decision
            (sync + async + multi-objective + model-execution paths pass
            this; preview endpoints intentionally omit).
        db: Open SQLAlchemy session for PSS lookup. Required when
            ``solver_name`` is provided; ignored otherwise.

    Returns:
        Final credit count (>= 1) — base × multiplier, rounded.
    """
    num_vars = len(problem.variables)
    num_int_bin = sum(1 for v in problem.variables if v.type.value in ("integer", "binary"))
    num_cons = len(problem.constraints)
    time_limit = problem.options.time_limit_seconds
    total, _ = compute_credits(num_vars, num_int_bin, num_cons, time_limit)

    if solver_name and db is not None:
        try:
            multiplier = PSS.get_float(
                db,
                f"pricing.solver_multiplier.{solver_name}",
                default=1.0,
            )
        except MissingSettingError:
            # Unknown solver names have no registered PSS multiplier key.
            # Fall back to 1.0 — the SolverNotFoundError raised by the
            # registry (downstream) will produce the correct 422 response.
            multiplier = 1.0
        return max(1, round(total * multiplier))
    return total


__all__ = ["FREE_TIME_LIMIT_SECONDS", "calculate_credits", "compute_credits"]
