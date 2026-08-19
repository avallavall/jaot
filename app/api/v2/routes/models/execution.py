"""Model execution endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session, defer

from app.api.deps import DBSession
from app.api.v2._access import execution_or_404
from app.api.v2._solver_limits import compute_celery_time_limits, resolve_solver_time_limit
from app.api.v2.auth import get_current_user
from app.api.v2.deps.solve_maintenance_gate import solve_maintenance_gate
from app.api.v2.solve_pipeline import wait_for_task
from app.api.v2.solver_errors import solver_unavailable
from app.domains.solver import execution_writer
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.services.solver_service import SolverService, get_solver_service
from app.domains.solver.services.template_engine import TemplateEngine, get_template_engine
from app.models import ExecutionStatus, ModelExecution, Organization, User
from app.models.model_project import ModelProject, ModelProjectListing
from app.models.trigger import SolveTrigger
from app.schemas.model import (
    AsyncExecutionResponse,
    ExecuteModelRequest,
    ExecutionCancelResponse,
    ExecutionListResponse,
    ExecutionStatusResponse,
    ExecutionSummaryResponse,
    ModelExecutionResponse,
)
from app.schemas.optimization import (
    OptimizationProblem,
)
from app.services.template_resolver import listing_to_template_dict
from app.shared.constants.execution_provenance import ORIGIN_MARKETPLACE
from app.shared.core.http_errors import CodedHTTPException
from app.shared.core.validation_message import validation_summary
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["execution"])


class PreviewRequest(BaseModel):
    input_data: dict[str, Any]


def _project_or_404(db: Session, model_id: str, org_id: str) -> ModelProject:
    """The org's active ModelProject, or 404 (identical detail cross-org — anti-oracle)."""
    project = (
        db.query(ModelProject)
        .filter(
            ModelProject.id == model_id,
            ModelProject.organization_id == org_id,
            ModelProject.status == "active",
        )
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Model not found or inactive")
    return project


def _resolve_generator_template(db: Session, project: ModelProject) -> dict[str, Any] | None:
    """The generator template a project executes through, if any.

    A fork (seeded from-marketplace) parametrizes through its SOURCE listing's
    generator facet; a project whose own listing carries a generator (officials)
    uses that. A plain project returns None and executes its draft content.
    """
    listing_id = (
        project.source_ref
        if project.source_type == "marketplace" and project.source_ref
        else project.id
    )
    listing = (
        db.query(ModelProjectListing)
        .filter(
            ModelProjectListing.model_project_id == listing_id,
            ModelProjectListing.generator_type.isnot(None),
        )
        .first()
    )
    return listing_to_template_dict(listing) if listing else None


@router.post("/{model_id}/preview", response_model=OptimizationProblem)
def preview_model(
    model_id: str,
    body: PreviewRequest,
    db: DBSession,
    current_user: User = Depends(get_current_user),
    template_engine: TemplateEngine = Depends(get_template_engine),
) -> OptimizationProblem:
    """Render a generator-backed model and return the OptimizationProblem without solving."""
    project = _project_or_404(db, model_id, current_user.organization_id)

    template = _resolve_generator_template(db, project)
    if template is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Model is not generator-backed — it has no input schema to preview. "
                "Open it in the studio to inspect its content."
            ),
        )

    return template_engine.render(template, body.input_data)


@router.post(
    "/{model_id}/execute",
    # Two shapes by design: the queue acknowledgement (``async_mode``), or the
    # completed execution. The 202-degrade path returns a JSONResponse, which
    # bypasses the response model entirely.
    response_model=ModelExecutionResponse | AsyncExecutionResponse,
    operation_id="execute_model",
    dependencies=[Depends(solve_maintenance_gate)],
)
def execute_model(
    model_id: str,
    body: ExecuteModelRequest,
    db: DBSession,
    current_user: User = Depends(get_current_user),
    solver: SolverService = Depends(get_solver_service),
    template_engine: TemplateEngine = Depends(get_template_engine),
    solver_name: str | None = Query(default=None, max_length=32),
) -> ModelExecutionResponse | dict[str, Any]:
    """Execute one of the organization's models with the provided input data.

    P1.5 fusion: ``model_id`` is a ModelProject. A generator-backed model (a
    fork of an official, or a project whose own listing carries a generator)
    renders ``input_data`` through the TemplateEngine; a plain model solves
    its draft content directly (``input_data`` must be empty — there is no
    input schema to fill).

    Optional ``solver_name`` selects the solver (``scip``, ``highs``,
    ``hexaly``) or ``auto`` routing; omit for the default.

    ADR-007 S6: both modes run on the async pipeline (``solve_model_async``).
    ``async_mode=false`` enqueues, waits up to the shared budget and returns
    the historic ``ModelExecutionResponse``; past the budget it degrades to
    202 + the async envelope (poll ``poll_url``). Sync ``def`` on purpose —
    the blocking wait belongs in the threadpool, never on the event loop.
    """
    project = _project_or_404(db, model_id, current_user.organization_id)

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    template = _resolve_generator_template(db, project)
    problem_data: dict[str, Any] | None = None
    if template is not None:
        # Render the problem first — auto-routing classification needs it.
        problem = template_engine.render(template, body.input_data)
    else:
        if body.input_data:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Model is not generator-backed — it takes no input_data. "
                    "Send an empty input_data to solve its current content, or "
                    "edit the model in the studio."
                ),
            )
        model_json = project.draft_model_json
        if not model_json:
            raise HTTPException(
                status_code=422,
                detail="Model has no content to solve. Build it in the studio first.",
            )
        try:
            problem = OptimizationProblem.model_validate(model_json)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=validation_summary(
                    exc, prefix="Stored model is not a valid optimization problem."
                ),
            ) from exc
        problem_data = problem.model_dump(mode="json")

    # Resolve "auto" to a concrete solver BEFORE queueing or solving.
    # Parity with /api/v2/solve (Phase 7.4 / D-11 / D-13): this endpoint used to
    # pass "auto" straight through to the registry, which raised
    # SolverNotFoundError("Solver 'auto' is not registered."). Resolve it here so
    # the rest of the flow only ever sees a concrete solver name.
    auto_route_reason: str | None = None
    fallback_triggered: bool = False
    if solver_name == "auto":
        from app.domains.solver.services.auto_router import select_solver  # noqa: PLC0415

        effective_solver_name, auto_route_reason, fallback_triggered = select_solver(
            problem, solver.parser
        )
    else:
        effective_solver_name = solver_name

    # D-11: direct hexaly selection + worker down → 503 up front.
    # No-op when the auto-router already fell back to SCIP.
    if not fallback_triggered:
        ensure_hexaly_worker_or_503(effective_solver_name)

    # Validate the concrete (post-routing) solver name up front — 422 like the
    # historic inline path. The worker re-binds the actual service itself.
    if effective_solver_name is not None:
        try:
            get_solver_service(solver_name=effective_solver_name)
        except (SolverNotFoundError, SolverUnavailableError) as exc:
            raise solver_unavailable(exc, effective_solver_name) from exc

    # Before input_data is frozen onto the row: Hexaly has no natural stopping
    # point, so a request that names no limit gets the configured default.
    problem.options.time_limit_seconds = resolve_solver_time_limit(
        db, effective_solver_name, problem.options.time_limit_seconds
    )

    execution = ModelExecution(
        id=generate_id("exe_"),
        model_project_id=model_id,
        organization_id=current_user.organization_id,
        executed_by_user_id=current_user.id,
        input_data=problem.model_dump(mode="json"),
        status=ExecutionStatus.PENDING.value,
        started_at=utcnow(),
        solver_name=effective_solver_name or DEFAULT_SOLVER_NAME,
        auto_route_reason=auto_route_reason,
        # Provenance: a model execution navigates back to its ModelProject.
        origin=ORIGIN_MARKETPLACE,
        source_kind="model_project",
        source_id=model_id,
    )
    db.add(execution)
    db.commit()

    # ADR-007 S6: BOTH modes run on the async pipeline — solve_model_async is
    # the single marketplace executor. Sync mode is a thin wrapper: enqueue,
    # wait up to the shared budget, shape the historic response (or 202).
    from app.domains.solver.tasks.solve_tasks import solve_model_async

    # solver_name has already been resolved ("auto" → concrete) above;
    # resolve_queue is a defense-in-depth check against future drift.
    try:
        target_queue = resolve_queue(effective_solver_name)
    except SolverNotFoundError as exc:
        # The stored error keeps the real reason: it is the operator's own record.
        execution_writer.apply_failed(execution, error=str(exc))
        db.commit()
        raise solver_unavailable(exc, effective_solver_name) from exc

    # W15/F-01: derive Celery soft/hard kill limits from the rendered
    # problem's own solver time limit so a hung worker child cannot pin
    # the queue forever (the soft-limit except-branch marks the execution
    # failed; the hard limit SIGKILLs and the reaper reconciles).
    soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)

    try:
        task = solve_model_async.apply_async(
            kwargs={
                "execution_id": execution.id,
                "model_id": model_id,
                "template": template,
                "input_data": body.input_data,
                "organization_id": current_user.organization_id,
                "solver_name": effective_solver_name,
                # Static (non-generator) models ship the validated problem —
                # the worker solves it directly instead of rendering a template.
                "problem_data": problem_data,
            },
            queue=target_queue,
            soft_time_limit=soft_limit,
            time_limit=hard_limit,
        )
    except Exception as exc:
        # Broker down or routing error — the ModelExecution is marked failed
        # so the dashboard reflects the outcome.
        logger.error("apply_async failed for execution %s: %s", execution.id, exc)
        execution_writer.apply_failed(execution, error=f"Failed to enqueue task: {exc}")
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue execution task. Please retry shortly.",
            },
        ) from exc

    execution.celery_task_id = task.id
    execution.is_async = True
    db.commit()

    envelope = {
        "id": execution.id,
        "execution_id": execution.id,
        "model_project_id": model_id,
        "status": "pending",
        "task_id": task.id,
        "ws_url": f"/api/v2/ws/executions/{execution.id}",
        "poll_url": f"/api/v2/models/async/{task.id}",
        "message": "Task queued for processing",
    }
    if body.async_mode:
        return envelope

    # Wrapped sync mode: bounded blocking wait (threadpool), then the exact
    # historic contract — or the 202 degrade past the budget (ADR-007).
    payload = wait_for_task(task)
    if payload is None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                **envelope,
                "message": (
                    "Solve still running after the wait budget — poll poll_url or "
                    "subscribe to ws_url for the result."
                ),
            },
        )
    return _shape_model_execution_response(db, execution, payload)


def _shape_model_execution_response(
    db: Session,
    execution: ModelExecution,
    payload: dict[str, Any] | BaseException,
) -> ModelExecutionResponse:
    """Map a finished ``solve_model_async`` run onto the historic sync contract.

    Production: the worker committed the terminal row before the task resolved —
    re-read it and serialize the exact row (byte-parity with the pre-ADR-007
    inline path). Under the eager test fixture the worker's write can be
    invisible to this session, so fall back to shaping from the task envelope.
    """
    try:
        db.refresh(execution)
    except Exception:
        logger.debug("Refresh failed shaping execution %s", execution.id, exc_info=True)
    if execution_writer.is_terminal(execution):
        return ModelExecutionResponse.model_validate(execution)

    if isinstance(payload, BaseException):
        # Hard task failure (propagate=False hands back the exception object);
        # mirror the worker's row shape.
        dynamic: dict[str, Any] = {
            "status": ExecutionStatus.FAILED.value,
            "error_message": str(payload),
        }
    elif payload.get("status") == "error":
        dynamic = {
            "status": ExecutionStatus.FAILED.value,
            "error_message": str(payload.get("error") or "Solver returned an error"),
            "result_data": payload.get("result_data"),
            "execution_time_ms": payload.get("execution_time_ms"),
            "solver_status": payload.get("solver_status"),
        }
    else:
        inner = payload.get("result")
        if not isinstance(inner, dict):
            inner = {}
        objective = inner.get("objective_value")
        dynamic = {
            "status": ExecutionStatus.COMPLETED.value,
            "result_data": inner or None,
            "execution_time_ms": payload.get("execution_time_ms"),
            "solver_status": inner.get("solver_status"),
            "objective_value": float(objective) if isinstance(objective, (int, float)) else None,
        }
    return ModelExecutionResponse(
        id=execution.id,
        model_project_id=execution.model_project_id,
        organization_model_id=execution.organization_model_id,
        input_data=execution.input_data or {},
        origin=execution.origin,
        source_kind=execution.source_kind,
        source_id=execution.source_id,
        created_at=execution.created_at,
        completed_at=utcnow(),
        **dynamic,
    )


@router.get("/async/{task_id}", response_model=ExecutionStatusResponse)
def get_async_execution_status(
    task_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the status of an async execution task."""
    from celery.result import AsyncResult

    from app.shared.core.celery_app import celery_app

    # Enforce tenant ownership BEFORE touching AsyncResult to prevent IDOR
    # (Phase 6 CR-02): without this guard any authenticated user could read
    # the progress/result/error payload of any task_id by bruteforcing or
    # guessing Celery task ids across tenants. The /solve/async/{task_id}
    # endpoint in app/api/v2/solve.py already applies this pattern.
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.celery_task_id == task_id,
            ModelExecution.organization_id == current_user.organization_id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=404,
            detail="Task not found or not authorized",
        )

    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING":
        return {
            "task_id": task_id,
            "execution_id": execution.id,
            "status": "pending",
            "message": "Task is waiting to be processed",
        }
    if result.state == "PROGRESS":
        # task_id/execution_id/status LAST — same reason as the solve poll
        # endpoint: the task's own progress meta carries a "status" that reads
        # "completed" on the final "Model found!" tick while Celery is still in
        # PROGRESS. Spread first, and that value overwrites "running", so the
        # client reads a completed payload with no result and reports a false
        # failure.
        info = result.info if isinstance(result.info, dict) else {}
        return {
            **info,
            "task_id": task_id,
            "execution_id": execution.id,
            "status": "running",
        }
    if result.state == "SUCCESS":
        celery_result = result.result

        if isinstance(celery_result, dict):
            inner_result = celery_result.get("result", celery_result)
            exec_time = celery_result.get("execution_time_ms")
            exec_id = celery_result.get("execution_id") or execution.id
        else:
            inner_result = celery_result
            exec_time = None
            exec_id = execution.id

        if exec_time is None:
            db.refresh(execution)
            exec_time = execution.execution_time_ms

        return {
            "task_id": task_id,
            "execution_id": exec_id,
            "status": "completed",
            "result": inner_result,
            "execution_time_ms": exec_time,
        }
    if result.state == "FAILURE":
        return {
            "task_id": task_id,
            "execution_id": execution.id,
            "status": "failed",
            "error": str(result.result),
        }
    return {
        "task_id": task_id,
        "execution_id": execution.id,
        "status": result.state.lower(),
    }


@router.post("/async/{task_id}/cancel", response_model=ExecutionCancelResponse)
def cancel_model_execution(
    task_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> ExecutionCancelResponse:
    """Cancel a running async model execution."""
    from celery.result import AsyncResult

    from app.shared.core.celery_app import celery_app

    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.celery_task_id == task_id,
            ModelExecution.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not execution:
        raise CodedHTTPException(
            status_code=404,
            detail="Execution not found or not authorized",
            code="execution.not_found",
        )

    result = AsyncResult(task_id, app=celery_app)

    if result.state in ["SUCCESS", "FAILURE"]:
        return ExecutionCancelResponse(
            task_id=task_id,
            execution_id=execution.id,
            cancelled=False,
            message=f"Task already {result.state.lower()}, cannot cancel",
        )

    # Mark the execution cancelled BEFORE revoking the Celery task so
    # solve_model_async's except handler sees the terminal row and preserves
    # the user-triggered cancellation. Locked re-read first (S6b): an unlocked
    # stale RUNNING here would clobber a COMPLETED the worker just committed.
    execution = execution_writer.refresh_locked(db, execution)
    execution_writer.apply_cancelled(execution)
    try:
        db.commit()
    except Exception:
        logger.warning(
            "Failed to mark execution %s as cancelled before revoke; proceeding with revoke anyway",
            execution.id,
            exc_info=True,
        )
        db.rollback()

    celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

    return ExecutionCancelResponse(
        task_id=task_id,
        execution_id=execution.id,
        cancelled=True,
        message="Execution cancelled",
    )


@router.get("/{model_id}/executions", response_model=ExecutionListResponse)
def list_model_executions(
    model_id: str,
    db: DBSession,
    status: str | None = Query(None),
    origin: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> ExecutionListResponse:
    """List execution history for a specific model (ModelProject)."""
    project = (
        db.query(ModelProject)
        .filter(
            ModelProject.id == model_id,
            ModelProject.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Model not found")

    # Typed column for new rows; the legacy org-model column still matches
    # historic executions because the P1.5 backfill preserved ids.
    query = db.query(ModelExecution).filter(
        ModelExecution.organization_id == current_user.organization_id,
        or_(
            ModelExecution.model_project_id == model_id,
            ModelExecution.organization_model_id == model_id,
        ),
    )

    if status:
        query = query.filter(ModelExecution.status == status)

    if origin:
        query = query.filter(ModelExecution.origin == origin)

    query = _without_payloads(query.order_by(ModelExecution.created_at.desc()))

    executions, total = paginate_query(query, page, page_size)

    items = [ExecutionSummaryResponse.model_validate(e) for e in executions]
    _attach_trigger_names(db, current_user.organization_id, executions, items)
    return ExecutionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def _without_payloads(query):
    """Leave ``input_data`` and ``result_data`` in the database.

    A list of runs shows status, model, objective, time and date. Loading the
    whole compiled problem and the whole solution for every row cost 37 MB of
    JSON for twenty rows, and up to 90 MB — enough to be one of the paths that
    pushed the API towards its memory ceiling. Deferring them means the columns
    are never read, not merely never serialised.
    """
    return query.options(defer(ModelExecution.input_data), defer(ModelExecution.result_data))


def _attach_trigger_names(
    db: Session,
    organization_id: str,
    executions: list[ModelExecution],
    items: list[ExecutionSummaryResponse],
) -> None:
    """Batch-fill each row's ``trigger_name`` from its trigger.

    The table used to read this out of ``input_data``, which is the only reason
    a list needed that column at all. One query by id, scoped to the
    organization so a foreign trigger id stays opaque.
    """
    trigger_ids = {e.trigger_id for e in executions if e.trigger_id}
    if not trigger_ids:
        return

    names = {
        row.id: row.name
        for row in db.query(SolveTrigger)
        .filter(
            SolveTrigger.id.in_(trigger_ids),
            SolveTrigger.organization_id == organization_id,
        )
        .all()
    }
    for execution, item in zip(executions, items, strict=True):
        if execution.trigger_id:
            item.trigger_name = names.get(execution.trigger_id)


def _attach_model_names(
    db: Session,
    organization_id: str,
    executions: list[ModelExecution],
    items: list[ExecutionSummaryResponse],
) -> None:
    """Batch-fill each row's ``model_name``/``model_author`` from its ModelProject.

    The ModelExecution row carries ids/provenance, not a display name. Every run
    traces to a ModelProject: the typed ``model_project_id``, the generic
    ``source_kind="model_project"`` + ``source_id`` (the universal async path), or —
    for historic rows — the legacy ``organization_model_id``, which the P1.5
    backfill preserved as the project id. One batch query fills names + authors.

    The lookup is scoped to ``organization_id``: ``source_id`` is client-supplied on
    the solve request, so a cross-org id must NOT resolve to another org's project
    name or author — it simply stays opaque.
    """

    def _mp_id(e: ModelExecution) -> str | None:
        return (
            e.model_project_id
            or (e.source_id if e.source_kind == "model_project" else None)
            or e.organization_model_id
        )

    mp_ids = {mp_id for e in executions if (mp_id := _mp_id(e))}

    mp_info: dict[str, tuple[str, str | None]] = {}
    if mp_ids:
        rows = (
            db.query(ModelProject)
            .filter(
                ModelProject.id.in_(mp_ids),
                ModelProject.organization_id == organization_id,
            )
            .all()
        )
        for mp in rows:
            mp_info[mp.id] = (mp.name, mp.created_by_name)

    for e, item in zip(executions, items, strict=True):
        mp_id = _mp_id(e)
        if mp_id and mp_id in mp_info:
            item.model_name, item.model_author = mp_info[mp_id]


@router.get("/executions/all", response_model=ExecutionListResponse)
def list_all_executions(
    db: DBSession,
    status: str | None = Query(None),
    origin: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> ExecutionListResponse:
    """List all executions for the organization."""
    query = db.query(ModelExecution).filter(
        ModelExecution.organization_id == current_user.organization_id,
    )

    if status:
        query = query.filter(ModelExecution.status == status)

    if origin:
        query = query.filter(ModelExecution.origin == origin)

    query = _without_payloads(query.order_by(ModelExecution.created_at.desc()))

    executions, total = paginate_query(query, page, page_size)

    items = [ExecutionSummaryResponse.model_validate(e) for e in executions]
    _attach_model_names(db, current_user.organization_id, executions, items)
    _attach_trigger_names(db, current_user.organization_id, executions, items)
    return ExecutionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/executions/{execution_id}",
    response_model=ModelExecutionResponse,
    operation_id="get_execution",
)
def get_execution(
    execution_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> ModelExecutionResponse:
    """Get details of a specific execution."""
    execution = execution_or_404(db, execution_id, current_user.organization_id)
    item = ModelExecutionResponse.model_validate(execution)
    # Same name resolution the list does — without it the detail page and the
    # printable report it generates showed "—" for a model the list names.
    _attach_model_names(db, current_user.organization_id, [execution], [item])
    return item
