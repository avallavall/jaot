"""Solver comparison endpoints — one problem, several solvers, identical terms.

Deliberately NOT riding ``enqueue_async_solve``. That path is one solve, and it
routes to the queue of the solver it resolved; a comparison is N solves that must
all land on the same machine, one after another, or their seconds are not
comparable. What this module does reuse is everything that path guards: the
instance caps, the daily quota, problem validation, and ``execution_writer`` as
the single writer of ``ModelExecution`` rows.

Quota: each solver counts as one execution (owner decision, 2026-08-14), so a
comparison consumes as many daily slots as it has runnable solvers. A comparison
that cannot afford all of them is rejected whole rather than run half — half a
table invites a conclusion the missing half might have contradicted.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import CurrentOrg, CurrentUser, DBSession, enforce_org_rate_limit
from app.domains.solver import execution_writer
from app.domains.solver.queue_routing import COMPARISON_QUEUE
from app.domains.solver.services.classify import classify
from app.domains.solver.services.comparison_service import (
    UNSUPPORTED_SOLVER_STATUS,
    SolvedColumn,
    SolverPlanEntry,
    build_comparison_problem,
    compute_agreement,
    normalize_solver_names,
    plan_comparison,
)
from app.models import ModelExecution, ModelProject, Organization, SolverComparison, User
from app.models.audit_log import AuditAction
from app.models.optimization_model import ExecutionStatus
from app.models.solver_comparison import DEFAULT_COMPARISON_THREADS, ComparisonStatus
from app.schemas.optimization import OptimizationProblem
from app.schemas.solver_comparison import (
    ComparisonAgreement,
    ComparisonDetail,
    ComparisonListResponse,
    ComparisonSolverResult,
    ComparisonSummary,
    ComparisonTerms,
    CreateComparisonRequest,
)
from app.schemas.tier import tier_cap_detail
from app.services.audit_service import log_action
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.services.solve_orchestrator import validate_problem
from app.shared.constants.execution_provenance import ORIGIN_COMPARISON
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/solvers/compare", tags=["solvers"])

#: Solver verdicts whose numbers are worth comparing against each other. An
#: infeasible or errored run has no solution to agree about.
_COMPARABLE_STATUSES = frozenset({"optimal", "feasible"})

_UNSUPPORTED_MESSAGES = {
    "integer_variables": "This solver cannot handle integer or binary variables.",
    "quadratic_terms": "This solver cannot handle quadratic terms.",
    "not_registered": "This solver is not installed on this server.",
    "not_available": "This solver cannot take part in a comparison on this server.",
}


# ──────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ComparisonDetail)
def create_comparison(
    payload: CreateComparisonRequest,
    db: DBSession,
    org: CurrentOrg,
    user: CurrentUser,
) -> ComparisonDetail:
    """Queue a comparison and return its table, every row still pending.

    Everything that can be decided without solving is decided here: which solvers
    can express the model, what settings they all get, and whether the quota
    covers the run. A solver that cannot express the model gets its row written
    straight to its verdict and never reaches the worker, so it costs no quota
    and no worker time.
    """
    enforce_org_rate_limit(db, org)

    solver_names = normalize_solver_names(payload.solver_names)
    if not solver_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No solver names given.",
        )

    problem, provenance = _resolve_problem(db, org, payload)

    settings = payload.settings
    problem = build_comparison_problem(
        problem,
        time_limit_seconds=settings.time_limit_seconds,
        gap_tolerance=settings.gap_tolerance,
        threads=DEFAULT_COMPARISON_THREADS,
    )
    problem = enforce_instance_caps(db, problem)
    # Whatever the caps did to the time limit is what every solver receives, so
    # the recorded terms are read back off the problem, not off the request.
    terms = ComparisonTerms(
        time_limit_seconds=problem.options.time_limit_seconds,
        gap_tolerance=problem.options.gap_tolerance,
        threads=problem.options.threads,
    )

    # Reject a malformed problem once, here, rather than once per solver on the
    # worker. Undefined variable references and inverted bounds are properties of
    # the model; no solver is going to disagree about them.
    validate_problem(problem)

    # Classified once here: the plan needs it to decide who can run, and the
    # comparison stores it so the page never re-parses the model on a poll.
    problem_class = classify(problem)
    plan = plan_comparison(problem, solver_names, problem_class)
    runnable = [entry for entry in plan if entry.will_run]
    if not runnable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "no_solver_can_run_this_model",
                "message": (
                    "None of the selected solvers can run this model. "
                    "Pick a solver that supports the model's variable types."
                ),
                "reasons": {entry.solver_name: entry.unsupported_reason for entry in plan},
            },
        )

    consume_daily_quota(db, org, len(runnable))

    comparison = SolverComparison(
        id=generate_id("cmp_"),
        organization_id=org.id,
        created_by_user_id=user.id,
        problem_data=problem.model_dump(mode="json"),
        problem_name=provenance.get("display_name") or problem.name,
        problem_class=problem_class.value,
        variable_count=len(problem.variables),
        constraint_count=len(problem.constraints),
        source_kind=provenance.get("source_kind"),
        source_id=provenance.get("source_id"),
        uploaded_filename=payload.uploaded_filename,
        model_project_id=provenance.get("model_project_id"),
        model_project_version_id=provenance.get("model_project_version_id"),
        time_limit_seconds=terms.time_limit_seconds,
        gap_tolerance=terms.gap_tolerance,
        threads=terms.threads,
        # Every solver asked for, runnable or not. The table has a row for each.
        solver_names=[entry.solver_name for entry in plan],
        status=ComparisonStatus.PENDING.value,
    )
    db.add(comparison)
    # Flush the parent before the children. ``comparison_id`` is set as a plain
    # string rather than through a relationship, so SQLAlchemy's unit of work
    # cannot see that the children depend on it and would happily INSERT them
    # first — straight into a foreign-key violation.
    db.flush()

    for entry in plan:
        insert_comparison_child(db, comparison, entry, problem, provenance, user)

    log_action(
        db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.SOLVE,
        target_type="solver_comparison",
        target_id=comparison.id,
        target_name=problem.name,
        metadata={"solvers": [entry.solver_name for entry in runnable]},
    )
    db.commit()

    enqueue_comparison(db, comparison)
    db.refresh(comparison)
    return _detail(db, comparison)


# ──────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────


@router.get("", response_model=ComparisonListResponse)
def list_comparisons(
    db: DBSession,
    org: CurrentOrg,
    _user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ComparisonListResponse:
    """This organization's comparisons, newest first."""
    base = db.query(SolverComparison).filter(SolverComparison.organization_id == org.id)
    total = base.count()
    rows = base.order_by(SolverComparison.created_at.desc()).limit(limit).offset(offset).all()
    return ComparisonListResponse(
        comparisons=[
            ComparisonSummary(
                id=row.id,
                status=row.status,
                problem_name=row.problem_name,
                solver_names=list(row.solver_names or []),
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ],
        total=total,
    )


@router.get("/{comparison_id}", response_model=ComparisonDetail)
def get_comparison(
    comparison_id: str,
    db: DBSession,
    org: CurrentOrg,
    _user: CurrentUser,
) -> ComparisonDetail:
    """One comparison and its table, whatever state it is in."""
    return _detail(db, _comparison_or_404(db, comparison_id, org))


# ──────────────────────────────────────────────────────────────
# Cancel
# ──────────────────────────────────────────────────────────────


@router.post("/{comparison_id}/cancel", response_model=ComparisonDetail)
def cancel_comparison(
    comparison_id: str,
    db: DBSession,
    org: CurrentOrg,
    _user: CurrentUser,
) -> ComparisonDetail:
    """Stop a comparison before its next solver starts.

    A solve already inside a solver cannot be interrupted from here, so the run
    in flight finishes and the worker stops before the next one. Columns that
    never got their turn are marked cancelled.
    """
    comparison = _comparison_or_404(db, comparison_id, org)
    cancel_comparison_rows(db, comparison)
    db.commit()
    db.refresh(comparison)
    return _detail(db, comparison)


#: Statuses a comparison never leaves. Cancelling one of these is a no-op.
TERMINAL_COMPARISON_STATUSES = frozenset(
    {
        ComparisonStatus.COMPLETED.value,
        ComparisonStatus.FAILED.value,
        ComparisonStatus.CANCELLED.value,
    }
)


def _close_pending_columns(db: Session, comparison: SolverComparison) -> None:
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
        execution_writer.apply_cancelled(execution, message="Comparison cancelled")


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
    _close_pending_columns(db, comparison)
    return True


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _resolve_problem(
    db: Session,
    org: Organization,
    payload: CreateComparisonRequest,
) -> tuple[OptimizationProblem, dict[str, str | None]]:
    """Return the problem to compare and where it came from.

    A named project is read from the database, never from the request body, so a
    caller cannot attach one project's name to another problem's numbers.
    """
    if payload.problem is not None:
        return payload.problem, {
            "source_kind": "imported_file" if payload.uploaded_filename else None,
            "source_id": None,
            "model_project_id": None,
            "model_project_version_id": None,
            # An uploaded file is known by its file name. Falling through to the
            # problem's own name shows whatever the exporter wrote in there,
            # which is often something like "obj".
            "display_name": payload.uploaded_filename or payload.problem.name,
        }

    project = (
        db.query(ModelProject)
        .filter(
            ModelProject.id == payload.project_id,
            ModelProject.organization_id == org.id,
        )
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    version_id: str | None = None
    if payload.version_id:
        from app.services import model_project_service as svc  # noqa: PLC0415

        version = svc.get_version_or_404(db, project.id, payload.version_id, org.id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        model_json = version.model_json
        version_id = version.id
    else:
        model_json = project.draft_model_json

    if not model_json:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project has no model to compare.",
        )
    try:
        problem = OptimizationProblem.model_validate(model_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_validation_detail(project.name, exc),
        ) from exc

    return problem, {
        "source_kind": "model_project",
        "source_id": project.id,
        "model_project_id": project.id,
        "model_project_version_id": version_id,
        # The name the user picked in the dropdown, not the name buried in the
        # stored problem — several real models carry "obj" in there.
        "display_name": project.name,
    }


#: How many of a validation failure's problems to name, and how long each may be.
#: A stored model can fail on hundreds of rows at once, and every Pydantic entry
#: carries the offending input with it — a grounded constraint runs to thousands
#: of characters. Dumping ``exc.errors()`` put that whole wall on the user's
#: screen and told them nothing they could act on.
_MAX_REPORTED_ERRORS = 3
_MAX_ERROR_LENGTH = 160


def _validation_detail(model_name: str, exc: ValidationError) -> dict[str, Any]:
    """Turn a Pydantic failure into something a person can read and act on."""
    errors = exc.errors(include_url=False, include_input=False, include_context=False)
    problems: list[str] = []
    for error in errors[:_MAX_REPORTED_ERRORS]:
        where = ".".join(str(part) for part in error.get("loc", ())) or "model"
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        if len(message) > _MAX_ERROR_LENGTH:
            message = f"{message[:_MAX_ERROR_LENGTH]}…"
        problems.append(f"{where}: {message}")

    remaining = max(0, len(errors) - _MAX_REPORTED_ERRORS)
    return {
        "error": "model_cannot_be_compared",
        "message": (
            f"'{model_name}' is not stored as a problem this platform can solve, so it "
            f"cannot be compared. The same model would fail an ordinary solve too."
        ),
        "problems": problems,
        "further_problems": remaining,
    }


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

    Known limitation: ``check_rate_limit`` consumes one slot per call and takes
    no cost argument, so a comparison rejected on its last solver has already
    spent the slots of the ones before it. Draining a few slots is the lesser
    fault against showing half a table, but it is a real cost and it is written
    down rather than hidden. The fix is a cost parameter on the rate limiter,
    which is shared by every endpoint and is not this feature's to change.
    """
    limits = PSS.get_instance_limits(db)
    daily = limits["max_daily_solves"]
    for _ in range(runs):
        allowed, _info = check_rate_limit(f"solve_daily:{org.id}", daily, daily)
        if allowed:
            continue
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="daily_solve_quota_exceeded",
                message=(
                    f"This comparison needs {runs:,} solves and you have reached "
                    f"this instance's daily limit of {daily:,}, which resets daily. "
                    f"Compare fewer solvers, or ask an administrator to raise the "
                    f"limit in Settings (instance_max_daily_solves; 0 means unlimited)."
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
        execution.error_message = _UNSUPPORTED_MESSAGES.get(reason, reason)
        execution.completed_at = execution.created_at
    return execution


def enqueue_comparison(db: Session, comparison: SolverComparison) -> None:
    """Hand the comparison to the single-slot comparison worker.

    The rows are already committed, so a broker failure leaves a comparison the
    user can see and retry rather than a silent nothing.
    """
    from app.domains.solver.tasks.comparison_tasks import run_solver_comparison  # noqa: PLC0415

    task_id = str(uuid4())
    comparison.celery_task_id = task_id
    try:
        run_solver_comparison.apply_async(
            kwargs={
                "comparison_id": comparison.id,
                "organization_id": comparison.organization_id,
            },
            task_id=task_id,
            queue=COMPARISON_QUEUE,
        )
        db.commit()
    except Exception as exc:
        logger.error("apply_async failed for comparison %s: %s", comparison.id, exc)
        db.rollback()
        comparison = db.merge(comparison)
        comparison.status = ComparisonStatus.FAILED.value
        comparison.error_message = f"Failed to enqueue comparison: {exc}"
        # And close its columns. They were written before the enqueue, so without
        # this they sit pending under a failed parent until the reaper's next
        # sweep a quarter of an hour later, and the page polls the whole time.
        _close_pending_columns(db, comparison)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue the comparison. Please retry shortly.",
            },
        ) from exc


def _comparison_or_404(db: Session, comparison_id: str, org: Organization) -> SolverComparison:
    comparison = (
        db.query(SolverComparison)
        .filter(
            SolverComparison.id == comparison_id,
            SolverComparison.organization_id == org.id,
        )
        .first()
    )
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison not found")
    return comparison


def _detail(db: Session, comparison: SolverComparison) -> ComparisonDetail:
    """Shape one comparison into the table the UI renders."""
    children = db.query(ModelExecution).filter(ModelExecution.comparison_id == comparison.id).all()
    by_solver = {child.solver_name: child for child in children}

    results = [
        solver_row(solver_name, by_solver.get(solver_name))
        for solver_name in (comparison.solver_names or [])
    ]

    columns = [
        SolvedColumn(
            solver_name=row.solver_name,
            objective_value=row.objective_value,
            solution=_solution_of(by_solver.get(row.solver_name)),
        )
        for row in results
        if row.solver_status in _COMPARABLE_STATUSES
    ]
    agreement = compute_agreement(columns) if columns else None

    return ComparisonDetail(
        id=comparison.id,
        status=comparison.status,
        problem_name=comparison.problem_name,
        batch_id=comparison.batch_id,
        source_kind=comparison.source_kind,
        source_id=comparison.source_id,
        uploaded_filename=comparison.uploaded_filename,
        model_project_id=comparison.model_project_id,
        model_project_version_id=comparison.model_project_version_id,
        dataset_id=comparison.dataset_id,
        dataset_name=comparison.dataset_name,
        settings=ComparisonTerms(
            time_limit_seconds=comparison.time_limit_seconds,
            gap_tolerance=comparison.gap_tolerance,
            threads=comparison.threads,
        ),
        problem_class=comparison.problem_class,
        variable_count=comparison.variable_count,
        constraint_count=comparison.constraint_count,
        machine_note=comparison.machine_note,
        results=results,
        agreement=(
            ComparisonAgreement(
                compared_solvers=agreement.compared_solvers,
                objectives_agree=agreement.objectives_agree,
                solutions_identical=agreement.solutions_identical,
                max_objective_delta=agreement.max_objective_delta,
                alternative_optima=agreement.alternative_optima,
            )
            if agreement is not None
            else None
        ),
        error_message=comparison.error_message,
        created_at=comparison.created_at,
        started_at=comparison.started_at,
        completed_at=comparison.completed_at,
    )


def solver_row(solver_name: str, execution: ModelExecution | None) -> ComparisonSolverResult:
    """One table row. A solver with no execution row is still shown, as pending."""
    if execution is None:
        return ComparisonSolverResult(solver_name=solver_name, status=ExecutionStatus.PENDING.value)

    result_data: dict[str, Any] = execution.result_data or {}
    return ComparisonSolverResult(
        solver_name=solver_name,
        execution_id=execution.id,
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


def _solution_of(execution: ModelExecution | None) -> dict[str, float] | None:
    """The variable assignment this execution found, if it found one.

    The key is ``model``, not ``solution`` — that is what ``to_result_data()``
    writes. ``file_export`` reads both because it also handles rows written
    before the key settled; nothing a comparison creates is that old.
    """
    if execution is None or not execution.result_data:
        return None
    solution = execution.result_data.get("model")
    return solution if isinstance(solution, dict) else None


__all__ = ["router"]
