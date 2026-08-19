"""Everything a solver comparison needs that is not a route.

Two surfaces create comparisons — a single one from ``/solvers/compare`` and one
per dataset from a matrix — and a third writes them from a Celery worker, which
compiles a matrix row long after the request that asked for it has gone. The
three used to reach into the route module for this, which put a task at the
mercy of an HTTP handler's imports; the rules live here instead and all three
call them.

The instance caps and the quota raise ``HTTPException`` because they are limits
the caller has to be told about, in the words the API already uses for every
other cap. The worker catches them and writes the sentence onto its row.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.domains.solver import execution_writer
from app.domains.solver.services.comparison_service import (
    UNSUPPORTED_SOLVER_STATUS,
    SolverPlanEntry,
)
from app.models import ModelExecution, Organization, SolverComparison, User
from app.models.optimization_model import ExecutionStatus
from app.models.solver_comparison import ComparisonStatus
from app.schemas.optimization import OptimizationProblem
from app.schemas.solver_comparison import ComparisonSolverResult
from app.schemas.tier import tier_cap_detail
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.constants.execution_provenance import ORIGIN_COMPARISON
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.utils.id_generator import generate_id

#: The sentence a "not supported" row shows. The reason code is what is stored;
#: this is only how it reads.
UNSUPPORTED_MESSAGES = {
    "integer_variables": "This solver cannot handle integer or binary variables.",
    "quadratic_terms": "This solver cannot handle quadratic terms.",
    "not_registered": "This solver is not installed on this server.",
    "not_available": "This solver cannot take part in a comparison on this server.",
}


TERMINAL_COMPARISON_STATUSES = frozenset(
    {
        ComparisonStatus.COMPLETED.value,
        ComparisonStatus.FAILED.value,
        ComparisonStatus.CANCELLED.value,
    }
)


def close_pending_columns(
    db: Session, comparison: SolverComparison, *, message: str = "Comparison cancelled"
) -> None:
    """Cancel the columns that had not started. Does not commit."""
    pending = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.comparison_id == comparison.id,
            ModelExecution.status == ExecutionStatus.PENDING.value,
        )
        .all()
    )
    for execution in pending:
        execution_writer.apply_cancelled(execution, message=message)


def cancel_comparison_rows(db: Session, comparison: SolverComparison) -> bool:
    """Mark a comparison cancelled and cancel the columns that never started.

    Does not commit — the caller decides the transaction, which is what lets a
    matrix cancel all of its rows in one. Returns whether anything changed.
    """
    if comparison.status in TERMINAL_COMPARISON_STATUSES:
        return False

    comparison.status = ComparisonStatus.CANCELLED.value
    # Only the columns that have not started. A running one is left alone: the
    # worker owns it and will write its real verdict.
    close_pending_columns(db, comparison)
    return True


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def enforce_instance_caps(db: Session, problem: OptimizationProblem) -> OptimizationProblem:
    """Apply the instance variable cap and time-limit ceiling.

    Mirrors what ``_enforce_tier_caps`` does for a single solve, minus the quota
    (charged per solver below). A clamped time limit is applied to the shared
    problem, so all solvers stay on equal terms after the clamp too.
    """
    limits = PSS.get_instance_limits(db)

    max_vars = limits["max_variables"]
    num_vars = len(problem.variables)
    if max_vars > 0 and num_vars > max_vars:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="variable_limit_exceeded",
                message=(
                    f"This model has {num_vars:,} variables and this instance is "
                    f"configured to allow up to {max_vars:,}. An administrator can "
                    f"raise or remove the limit in Settings (instance_max_variables; "
                    f"0 means unlimited)."
                ),
                limit=max_vars,
                current_value=num_vars,
                setting_key="instance_max_variables",
            ),
        )

    ceiling = limits["max_solve_time_seconds"]
    if ceiling > 0 and problem.options.time_limit_seconds > ceiling:
        problem = problem.model_copy(
            update={"options": problem.options.model_copy(update={"time_limit_seconds": ceiling})}
        )
    return problem


def consume_daily_quota(db: Session, org: Organization, runs: int) -> None:
    """Charge ``runs`` daily solve slots, or reject the whole comparison.

    All ``runs`` slots are taken in one call, so a comparison the quota cannot
    cover costs nothing (D-30). This used to call the limiter once per solver:
    a matrix of twelve datasets by four solvers asked for forty-eight slots
    one at a time, and a user with forty-seven left lost all forty-seven to a
    launch that was then refused.
    """
    limits = PSS.get_instance_limits(db)
    daily = limits["max_daily_solves"]
    allowed, info = check_rate_limit(f"solve_daily:{org.id}", daily, daily, cost=runs)
    if not allowed:
        left = int((info or {}).get("remaining", 0))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="daily_solve_quota_exceeded",
                # Written for whoever hit the limit, not for whoever can raise
                # it. The setting key stays in `setting_key` below, where an
                # operator or an API client can read it; naming it in the
                # sentence told a plain member to go and edit something they
                # cannot see. "needs 1 solves" was the other half of it.
                message=(
                    f"This comparison needs {runs:,} "
                    f"{'solve' if runs == 1 else 'solves'} and "
                    f"{left:,} of today's {daily:,} "
                    f"{'is' if left == 1 else 'are'} left. It resets tomorrow. "
                    f"Compare fewer solvers, or ask an administrator to raise the limit."
                ),
                limit=daily,
                setting_key="instance_max_daily_solves",
            ),
        )


def insert_comparison_child(
    db: Session,
    comparison: SolverComparison,
    entry: SolverPlanEntry,
    problem: OptimizationProblem,
    provenance: dict[str, str | None],
    #: None when a matrix row is written by its worker and the account that
    #: launched it has since been deleted. The row still runs; it just records
    #: nobody, exactly as ``executed_by_user_id`` being nullable already allows.
    user: User | None,
) -> ModelExecution:
    """Write one column's execution row: pending if it runs, terminal if it cannot."""
    execution = execution_writer.insert_pending(
        db,
        execution_id=generate_id("exe_"),
        organization_id=comparison.organization_id,
        celery_task_id="",
        input_data=problem.model_dump(mode="json"),
        solver_name=entry.solver_name,
        executed_by_user_id=user.id if user is not None else None,
        origin=ORIGIN_COMPARISON,
        source_kind=provenance.get("source_kind"),
        source_id=provenance.get("source_id"),
        model_project_id=provenance.get("model_project_id"),
        model_project_version_id=provenance.get("model_project_version_id"),
        # A matrix row was compiled against one dataset, and the run history has a
        # column for it. Read off the comparison rather than the provenance dict:
        # the parent is where the dataset was resolved and snapshotted.
        dataset_id=comparison.dataset_id,
        dataset_name=comparison.dataset_name,
    )
    execution.comparison_id = comparison.id
    # No Celery task of its own: the comparison task solves every column, so the
    # column has no task id to reconcile against. NULL says that; an empty string
    # would look like an id nobody can find. The reaper judges these rows by their
    # parent instead (see _comparison_still_alive).
    execution.celery_task_id = None
    if not entry.will_run:
        reason = entry.unsupported_reason or "not_available"
        execution.status = ExecutionStatus.FAILED.value
        execution.solver_status = UNSUPPORTED_SOLVER_STATUS
        execution.result_data = {"unsupported_reason": reason}
        execution.error_message = UNSUPPORTED_MESSAGES.get(reason, reason)
        execution.completed_at = execution.created_at
    return execution


def solver_row(solver_name: str, execution: ModelExecution | None) -> ComparisonSolverResult:
    """One table row. A solver with no execution row is still shown, as pending."""
    if execution is None:
        return ComparisonSolverResult(solver_name=solver_name, status=ExecutionStatus.PENDING.value)

    result_data: dict[str, Any] = execution.result_data or {}
    return ComparisonSolverResult(
        solver_name=solver_name,
        execution_id=execution.id,
        solver_version=result_data.get("solver_version"),
        status=execution.status,
        solver_status=execution.solver_status,
        unsupported_reason=result_data.get("unsupported_reason"),
        objective_value=execution.objective_value,
        gap=result_data.get("gap"),
        dual_bound=result_data.get("dual_bound"),
        iterations=result_data.get("iterations"),
        nodes=result_data.get("nodes"),
        wall_time_ms=execution.execution_time_ms,
        solver_time_seconds=result_data.get("solve_time_seconds"),
        error_message=execution.error_message,
    )
