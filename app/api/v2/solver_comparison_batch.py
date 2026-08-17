"""The matrix: several datasets crossed with several solvers.

One comparison answers "which solver is faster on this problem". A model whose
data changes every month has no single answer to that, and picking a solver from
one month's numbers is how you pick the wrong one. This module runs the same
JModel source against N datasets and M solvers and hands back the whole grid.

**A row is a comparison, not a new kind of thing.** Each dataset gets its own
``SolverComparison``, with its own snapshot, its own terms and its own child
executions, tied to its siblings by ``batch_id``. Everything a single comparison
already guarantees therefore holds inside a row: the same time limit for every
column, a verdict for a solver that cannot run, and the whole set solved one at a
time on one machine. What a batch adds is the launch, the grid and the cancel.

**Rows run as N tasks, not one.** They all land on ``solve_compare``, whose
worker has ``--concurrency=1``, so the sequential guarantee survives; splitting
them means one dataset that blows up does not take the rest of the grid with it.

**Compiled here, not in the browser.** The source lives on the server and so does
the data, and the largest real scenarios ground to tens of megabytes. Same reason
``POST /projects/{id}/datasets/{id}/solve`` compiles server-side (ADR-007 S7).

This module lives in ``app.api`` rather than the solver domain because it needs
the JModel compiler, and a solver-domain module importing ``app.domains.dsl``
would breach the ``domains-independent`` import contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import CurrentOrg, CurrentUser, DBSession, enforce_org_rate_limit
from app.api.v2.solver_comparison import (
    cancel_comparison_rows,
    consume_daily_quota,
    enforce_instance_caps,
    solver_row,
)
from app.domains.dsl import JModelData, JModelError, compile_jmodel
from app.domains.solver import execution_writer
from app.domains.solver.queue_routing import COMPARISON_QUEUE
from app.domains.solver.services.classify import classify
from app.domains.solver.services.comparison_service import (
    SolverPlanEntry,
    build_comparison_problem,
    normalize_solver_names,
    plan_comparison,
)
from app.models import ModelExecution, ModelProject, ModelProjectDataset, Organization, User
from app.models.audit_log import AuditAction
from app.models.optimization_model import ExecutionStatus
from app.models.solver_comparison import (
    DEFAULT_COMPARISON_THREADS,
    ComparisonStatus,
    SolverComparison as Comparison,
)
from app.schemas.solver_comparison import (
    ComparisonBatchDetail,
    ComparisonBatchListResponse,
    ComparisonBatchSummary,
    ComparisonMatrixRow,
    ComparisonTerms,
    CreateComparisonBatchRequest,
)
from app.services import model_project_service as project_svc
from app.services.audit_service import log_action
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.services.solve_orchestrator import validate_problem
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

#: Declared BEFORE the single-comparison router in ``router.py``. Both live under
#: ``/solvers/compare``, and the single one owns ``/{comparison_id}`` — included
#: the other way round, every path here would be swallowed by it and answered
#: "Comparison not found". A contract test guards the order.
router = APIRouter(prefix="/solvers/compare/batches", tags=["solvers"])


@dataclass(frozen=True)
class _ModelCheck:
    """What one compile of the model tells us about every row of the matrix.

    Which solvers can express the model, and therefore how many solves the matrix
    is going to cost, are properties of the SOURCE: the variable types and the
    shape of every expression are declared there, and the data only fills in
    numbers. So one dataset answers both questions for all of them, and the rest
    are compiled on the worker.
    """

    plan: list[SolverPlanEntry]

    @property
    def runnable(self) -> int:
        return sum(1 for entry in self.plan if entry.will_run)


# ──────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ComparisonBatchDetail)
def create_batch(
    payload: CreateComparisonBatchRequest,
    db: DBSession,
    org: CurrentOrg,
    user: CurrentUser,
) -> ComparisonBatchDetail:
    """Queue a matrix and return it with every cell still pending.

    The launch writes the rows and nothing else. Compiling every dataset here
    would put the whole cost of the model in front of the user before the page
    could even show a grid — measured at 28 seconds and 57 MB for three datasets
    of 22,500 variables, and past a proxy's ceiling at twelve. Each row is
    compiled by its own worker instead.

    What still happens here is one compile of the FIRST dataset. It is what says
    the model can be solved at all, which solvers can express it, and therefore
    what the matrix costs against the daily quota — all three are properties of
    the source rather than of the data, so one dataset answers for every row.
    """
    enforce_org_rate_limit(db, org)

    solver_names = normalize_solver_names(payload.solver_names)
    if not solver_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No solver names given."
        )

    project = _project_or_404(db, payload.project_id, org)
    source, version_id = _source_of(db, project, org, payload.version_id)
    datasets = _datasets_or_404(db, project, org, payload.dataset_ids)

    check = _check_model(db, source, datasets[0], payload, solver_names)
    if check.runnable == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "no_solver_can_run_this_model",
                "message": (
                    "None of the selected solvers can run this model. "
                    "Pick a solver that supports the model's variable types."
                ),
                "reasons": {entry.solver_name: entry.unsupported_reason for entry in check.plan},
            },
        )

    # Charged once for the whole grid, before anything is written: a matrix that
    # cannot afford its last row is rejected while it is still free to reject.
    consume_daily_quota(db, org, check.runnable * len(datasets))

    batch_id = generate_id("cmb_")
    comparisons = [
        _write_row(db, batch_id, position, dataset, check, project, version_id, payload, user)
        for position, dataset in enumerate(datasets)
    ]

    log_action(
        db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.SOLVE,
        target_type="solver_comparison_batch",
        target_id=batch_id,
        target_name=project.name,
        metadata={
            "solvers": solver_names,
            "datasets": [dataset.name for dataset in datasets],
            "runs": check.runnable * len(datasets),
        },
    )
    db.commit()

    for comparison in comparisons:
        try:
            enqueue_preparation(db, comparison)
        except HTTPException:
            # The row is already marked failed with the broker error. The rest of
            # the matrix still runs, and the failed row says why it did not.
            logger.warning("Matrix %s: row %s could not be queued", batch_id, comparison.id)
            _abandon_row(db, comparison)

    return _batch_detail(db, batch_id, org)


def enqueue_preparation(db: Session, comparison: Comparison) -> None:
    """Hand one row to the worker that will compile it.

    Same shape as ``enqueue_comparison`` and the same failure handling: the rows
    are already committed, so a broker failure leaves a row the user can see
    rather than a silent nothing.
    """
    from app.tasks.comparison_prepare import prepare_comparison_row  # noqa: PLC0415

    task_id = str(uuid4())
    comparison.celery_task_id = task_id
    try:
        prepare_comparison_row.apply_async(
            kwargs={
                "comparison_id": comparison.id,
                "organization_id": comparison.organization_id,
            },
            task_id=task_id,
            queue=COMPARISON_QUEUE,
        )
        db.commit()
    except Exception as exc:
        logger.error("apply_async failed for row %s: %s", comparison.id, exc)
        db.rollback()
        comparison = db.merge(comparison)
        comparison.status = ComparisonStatus.FAILED.value
        comparison.error_message = f"Failed to enqueue this row: {exc}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue the matrix. Please retry shortly.",
            },
        ) from exc


def _abandon_row(db: Session, comparison: Comparison) -> None:
    """Close the cells of a row that never reached the queue.

    Without this the row reads "failed" while its cells stay pending forever,
    and the page keeps polling for a worker that was never told to start.
    """
    pending = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.comparison_id == comparison.id,
            ModelExecution.status == ExecutionStatus.PENDING.value,
        )
        .all()
    )
    for execution in pending:
        execution_writer.apply_cancelled(execution, message="Row was never queued")
    db.commit()


# ──────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────


@router.get("", response_model=ComparisonBatchListResponse)
def list_batches(
    db: DBSession,
    org: CurrentOrg,
    _user: CurrentUser,
    project_id: str | None = Query(default=None, description="Only this project's matrices."),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ComparisonBatchListResponse:
    """This organization's matrices, newest first."""
    groups = db.query(Comparison.batch_id, func.min(Comparison.created_at).label("started")).filter(
        Comparison.organization_id == org.id,
        Comparison.batch_id.isnot(None),
    )
    if project_id:
        groups = groups.filter(Comparison.model_project_id == project_id)
    groups = groups.group_by(Comparison.batch_id)

    total = groups.count()
    page = groups.order_by(func.min(Comparison.created_at).desc()).limit(limit).offset(offset).all()
    batch_ids = [row.batch_id for row in page]
    if not batch_ids:
        return ComparisonBatchListResponse(batches=[], total=total)

    rows = _rows_of(db, batch_ids, org)
    summaries: list[ComparisonBatchSummary] = []
    for batch_id in batch_ids:
        members = rows.get(batch_id, [])
        if not members:
            continue
        first = members[0]
        summaries.append(
            ComparisonBatchSummary(
                batch_id=batch_id,
                status=_derive_status([m.status for m in members]),
                project_id=first.model_project_id,
                project_name=first.problem_name,
                dataset_count=len(members),
                solver_names=list(first.solver_names or []),
                created_at=min(m.created_at for m in members),
                completed_at=_completed_at(members),
            )
        )
    return ComparisonBatchListResponse(batches=summaries, total=total)


@router.get("/{batch_id}", response_model=ComparisonBatchDetail)
def get_batch(
    batch_id: str,
    db: DBSession,
    org: CurrentOrg,
    _user: CurrentUser,
) -> ComparisonBatchDetail:
    """One matrix, whatever state it is in. This is what the page polls."""
    return _batch_detail(db, batch_id, org)


# ──────────────────────────────────────────────────────────────
# Cancel
# ──────────────────────────────────────────────────────────────


@router.post("/{batch_id}/cancel", response_model=ComparisonBatchDetail)
def cancel_batch(
    batch_id: str,
    db: DBSession,
    org: CurrentOrg,
    _user: CurrentUser,
) -> ComparisonBatchDetail:
    """Stop every row that has not finished.

    A solve already inside a solver cannot be interrupted, so the run in flight
    finishes and nothing after it starts.
    """
    members = _members_or_404(db, batch_id, org)
    for comparison in members:
        cancel_comparison_rows(db, comparison)
    db.commit()
    return _batch_detail(db, batch_id, org)


# ──────────────────────────────────────────────────────────────
# Building a launch
# ──────────────────────────────────────────────────────────────


def _project_or_404(db: Session, project_id: str, org: Organization) -> ModelProject:
    project = (
        db.query(ModelProject)
        .filter(ModelProject.id == project_id, ModelProject.organization_id == org.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _source_of(
    db: Session, project: ModelProject, org: Organization, version_id: str | None
) -> tuple[str, str | None]:
    """The JModel source to compile, and the version it came from.

    A matrix needs a source, not a flat model: a grounded model has no data left
    to swap, so every row would be the same problem under a different name.
    """
    if version_id:
        version = project_svc.get_version_or_404(db, project.id, version_id, org.id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        source = version.dsl_source
    else:
        source = project.draft_dsl_source

    if not source or not source.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "project_has_no_jmodel_source",
                "message": (
                    "This model has no JModel source. A matrix compiles the source "
                    "against each dataset, so a flat or imported model has nothing "
                    "for the datasets to fill."
                ),
            },
        )
    return source, (version_id if version_id else None)


def _datasets_or_404(
    db: Session, project: ModelProject, org: Organization, dataset_ids: list[str]
) -> list[ModelProjectDataset]:
    """The named datasets, in the order asked for, duplicates dropped."""
    seen: set[str] = set()
    datasets: list[ModelProjectDataset] = []
    for dataset_id in dataset_ids:
        if dataset_id in seen:
            continue
        seen.add(dataset_id)
        dataset = project_svc.get_dataset_or_404(db, dataset_id, org.id, project_id=project.id)
        if dataset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        datasets.append(dataset)
    return datasets


def _check_model(
    db: Session,
    source: str,
    dataset: ModelProjectDataset,
    payload: CreateComparisonBatchRequest,
    solver_names: list[str],
) -> _ModelCheck:
    """Compile one dataset to learn what the whole matrix will cost.

    The one compile the launch still does. It fails the request when the model
    cannot be solved at all — a source that does not compile, a model past the
    instance's variable cap, an undefined variable reference — because those are
    the failures worth stopping for, and every row would hit them identically.

    A dataset that does not FILL the model is a different matter and is not
    stopped here: with a dozen datasets in the request, one of them being
    incomplete says nothing about the other eleven, so that row fails on its own
    worker and stays in the grid saying so.
    """
    try:
        problem = compile_jmodel(source, data=JModelData.from_json(dataset.data_json))
    except JModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "dataset_did_not_compile",
                "dataset_name": dataset.name,
                "message": exc.message,
                "position": exc.position,
            },
        ) from exc

    problem = build_comparison_problem(
        problem,
        time_limit_seconds=payload.settings.time_limit_seconds,
        gap_tolerance=payload.settings.gap_tolerance,
        threads=DEFAULT_COMPARISON_THREADS,
    )
    try:
        problem = enforce_instance_caps(db, problem)
        validate_problem(problem)
    except HTTPException as exc:
        raise _blame_dataset(exc, dataset.name) from exc

    return _ModelCheck(plan=plan_comparison(problem, solver_names, classify(problem)))


def _blame_dataset(exc: HTTPException, dataset_name: str) -> HTTPException:
    """The same failure, saying which dataset produced it."""
    detail = exc.detail
    blamed = (
        {**detail, "dataset_name": dataset_name}
        if isinstance(detail, dict)
        else {"message": str(detail), "dataset_name": dataset_name}
    )
    return HTTPException(status_code=exc.status_code, detail=blamed)


def _write_row(
    db: Session,
    batch_id: str,
    position: int,
    dataset: ModelProjectDataset,
    check: _ModelCheck,
    project: ModelProject,
    version_id: str | None,
    payload: CreateComparisonBatchRequest,
    user: User,
) -> Comparison:
    """Write one row of the grid. No problem and no cells yet — its worker compiles
    the dataset and writes both.

    The terms are stored now rather than read back off a compiled problem,
    because there is no compiled problem here. They are what the worker will
    stamp onto it, so what the page shows above the grid is what every solver
    will receive.
    """
    limits = PSS.get_instance_limits(db)
    ceiling = limits["max_solve_time_seconds"]
    time_limit = payload.settings.time_limit_seconds
    if ceiling > 0 and time_limit > ceiling:
        time_limit = ceiling

    comparison = Comparison(
        id=generate_id("cmp_"),
        organization_id=project.organization_id,
        created_by_user_id=user.id,
        problem_data=None,
        # The project name, not the dataset's: the row header shows the dataset
        # and a cell opened on its own shows both.
        problem_name=project.name,
        source_kind="model_project",
        source_id=project.id,
        model_project_id=project.id,
        model_project_version_id=version_id,
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        time_limit_seconds=time_limit,
        gap_tolerance=payload.settings.gap_tolerance,
        threads=DEFAULT_COMPARISON_THREADS,
        # Every solver asked for, so the grid has its columns from the first
        # render. Which of them can actually run is decided per row by its worker.
        solver_names=[entry.solver_name for entry in check.plan],
        status=ComparisonStatus.PENDING.value,
        batch_id=batch_id,
        batch_position=position,
    )
    db.add(comparison)
    return comparison


# ──────────────────────────────────────────────────────────────
# Reading a matrix back
# ──────────────────────────────────────────────────────────────


def _members_or_404(db: Session, batch_id: str, org: Organization) -> list[Comparison]:
    members = (
        db.query(Comparison)
        .filter(Comparison.batch_id == batch_id, Comparison.organization_id == org.id)
        .order_by(Comparison.batch_position, Comparison.created_at)
        .all()
    )
    if not members:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison not found")
    return members


def _rows_of(db: Session, batch_ids: list[str], org: Organization) -> dict[str, list[Comparison]]:
    """Every member of several batches at once, grouped, in row order."""
    members = (
        db.query(Comparison)
        .filter(Comparison.batch_id.in_(batch_ids), Comparison.organization_id == org.id)
        .order_by(Comparison.batch_position, Comparison.created_at)
        .all()
    )
    grouped: dict[str, list[Comparison]] = {}
    for member in members:
        grouped.setdefault(member.batch_id or "", []).append(member)
    return grouped


def _batch_detail(db: Session, batch_id: str, org: Organization) -> ComparisonBatchDetail:
    """Shape a matrix into the grid the page renders.

    Two queries whatever the size of the grid: the page polls this every couple
    of seconds while it runs, and a query per row would multiply that by twelve.
    """
    members = _members_or_404(db, batch_id, org)
    executions = (
        db.query(ModelExecution)
        .filter(ModelExecution.comparison_id.in_([m.id for m in members]))
        .all()
    )
    by_comparison: dict[str, dict[str, ModelExecution]] = {}
    for execution in executions:
        columns = by_comparison.setdefault(execution.comparison_id or "", {})
        columns[execution.solver_name] = execution

    first = members[0]
    rows = [
        ComparisonMatrixRow(
            comparison_id=member.id,
            dataset_id=member.dataset_id,
            dataset_name=member.dataset_name,
            status=member.status,
            problem_class=member.problem_class,
            variable_count=member.variable_count,
            constraint_count=member.constraint_count,
            error_message=member.error_message,
            results=[
                solver_row(solver_name, by_comparison.get(member.id, {}).get(solver_name))
                for solver_name in (member.solver_names or [])
            ],
        )
        for member in members
    ]

    return ComparisonBatchDetail(
        batch_id=batch_id,
        status=_derive_status([m.status for m in members]),
        project_id=first.model_project_id,
        project_name=first.problem_name,
        model_project_version_id=first.model_project_version_id,
        settings=ComparisonTerms(
            time_limit_seconds=first.time_limit_seconds,
            gap_tolerance=first.gap_tolerance,
            threads=first.threads,
        ),
        solver_names=list(first.solver_names or []),
        machine_note=next((m.machine_note for m in members if m.machine_note), None),
        rows=rows,
        created_at=min(m.created_at for m in members),
        completed_at=_completed_at(members),
    )


def _derive_status(statuses: list[str]) -> str:
    """The matrix's own state, read off its rows.

    No stored column: a batch that kept its own status would need every row's
    writer to update it, and the row writers are Celery tasks in another process.
    Derived cannot drift.
    """
    if not statuses:
        return ComparisonStatus.PENDING.value
    if all(s == ComparisonStatus.PENDING.value for s in statuses):
        return ComparisonStatus.PENDING.value
    if any(s in (ComparisonStatus.PENDING.value, ComparisonStatus.RUNNING.value) for s in statuses):
        return ComparisonStatus.RUNNING.value
    if all(s == ComparisonStatus.FAILED.value for s in statuses):
        return ComparisonStatus.FAILED.value
    if any(s == ComparisonStatus.CANCELLED.value for s in statuses):
        return ComparisonStatus.CANCELLED.value
    return ComparisonStatus.COMPLETED.value


def _completed_at(members: list[Comparison]) -> datetime | None:
    """When the last row finished, or None while any row is still going."""
    stamps = [m.completed_at for m in members]
    if not stamps or any(stamp is None for stamp in stamps):
        return None
    return max(stamp for stamp in stamps if stamp is not None)


__all__ = ["router"]
