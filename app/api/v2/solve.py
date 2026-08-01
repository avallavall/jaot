"""Universal Solve Endpoint -- thin route wrappers over the ONE async pipeline (ADR-007)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import DBSession, OptionalRequireSolver, enforce_org_rate_limit
from app.api.v2._access import execution_or_404
from app.api.v2.deps.solve_maintenance_gate import solve_maintenance_gate
from app.api.v2.solve_pipeline import (
    _enqueue_multi_objective_async,
    apply_solution_filter,
    enqueue_async_solve,
    shape_sync_result,
    wait_for_task,
)
from app.domains.solver import execution_writer
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
)
from app.domains.solver.services import SolverService, get_solver_service
from app.models import ModelExecution, Organization
from app.schemas.optimization import (
    AsyncSolveCancelResponse,
    AsyncSolveEnvelope,
    AsyncSolveStatusResponse,
    InfeasibilityAnalysis,
    MultiObjectiveConfig,
    MultiObjectiveResult,
    OptimizationProblem,
    OptimizationResult,
    ProblemValidationResponse,
    SolverStatus,
)
from app.services.idempotency import idempotency_execution_id
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.services.solve_orchestrator import (
    validate_problem,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/solve", tags=["solve"])


def _is_verbose(request: Request) -> bool:
    """Return True when an admin caller sent ``X-Jaot-Debug: true``."""
    if request.headers.get("X-Jaot-Debug", "").lower() != "true":
        return False
    user = getattr(request.state, "user", None)
    return user is not None and getattr(user, "is_admin", False)


def _error_response(
    error_code: str, message: str, request: Request, **extra: Any
) -> dict[str, Any]:
    """Build error response dict, adding verbose details when X-Jaot-Debug: true."""
    response: dict[str, Any] = {"error": error_code, "message": message}
    if _is_verbose(request):
        response["details"] = extra
    return response


class MultiObjectiveSolveRequest(BaseModel):
    """Request body for the multi-objective solve endpoint."""

    problem: OptimizationProblem
    config: MultiObjectiveConfig


@router.post(
    "",
    response_model=OptimizationResult,
    operation_id="solve_problem",
    dependencies=[Depends(solve_maintenance_gate)],
)
@router.post(
    "/",
    response_model=OptimizationResult,
    dependencies=[Depends(solve_maintenance_gate)],
)
def solve_optimization_problem(  # def: blocks on the queued result (ADR-007 S2)
    problem: OptimizationProblem,
    request: Request,
    db: DBSession,
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
    solution_filter: Literal["nonzero"] | None = Query(
        default=None,
        description=(
            "Compact solution: 'nonzero' omits near-zero variables from the "
            "response (variables_omitted reports the count). The persisted "
            "execution keeps the full solution."
        ),
    ),
) -> Any:
    """Solve an optimization problem (universal endpoint).

    ADR-007 S2 — async-under-the-hood: the request rides the ONE async pipeline
    (pending ModelExecution row, Celery worker) and waits for
    the result in the threadpool. The contract is unchanged: the classic
    ``OptimizationResult`` on completion, ``Idempotency-Key`` honored (a retry
    returns the persisted result without re-solving). A solve
    that outlives the wait budget returns 202 + the task envelope — poll or
    subscribe like any async client (previously such solves died at proxy or
    orchestrator timeouts).
    """
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    enforce_org_rate_limit(db, org)

    # Idempotency: if a key is present, derive an execution_id that binds
    # (org_id, key, request body). Reusing the same key with a DIFFERENT
    # body yields a different id and executes fresh instead of returning
    # the wrong cached result.
    idempotency_key = request.headers.get("Idempotency-Key") or request.headers.get(
        "idempotency-key"
    )
    idem_exe_id: str | None = None
    if idempotency_key:
        body_canonical = problem.model_dump_json()
        idem_exe_id = idempotency_execution_id(idempotency_key, org.id, body_canonical)
        existing = (
            db.query(ModelExecution)
            .filter(
                ModelExecution.id == idem_exe_id,
                ModelExecution.organization_id == org.id,
            )
            .first()
        )
        if existing is not None:
            # NEW under async-under-the-hood: the pending row exists from enqueue
            # time, so an idempotent retry can race the original IN FLIGHT.
            # Attach to its task instead of reporting a bogus incomplete result.
            if existing.status in ("pending", "running") and existing.celery_task_id:
                return apply_solution_filter(
                    _attach_to_inflight_execution(db=db, org=org, existing=existing),
                    solution_filter,
                )
            rd = existing.result_data or {}
            # Default to ERROR on missing status: a cached execution with no
            # solver_status in result_data is by definition incomplete (the
            # task crashed before persisting), and returning a fake "optimal"
            # would mask the failure on retry.
            return apply_solution_filter(
                OptimizationResult(
                    status=SolverStatus(rd.get("solver_status", SolverStatus.ERROR.value)),
                    objective_value=rd.get("objective_value"),
                    solution=rd.get("model"),
                    solve_time_seconds=rd.get("solve_time_seconds", 0.0),
                    gap=rd.get("gap"),
                    error_message=existing.error_message,
                    execution_id=existing.id,
                ),
                solution_filter,
            )

    enqueued = enqueue_async_solve(
        db=db,
        org=org,
        user=getattr(request.state, "user", None),
        problem=problem,
        workspace_id=workspace_member.workspace_id if workspace_member else None,
        solver_name_param=solver_name,
        origin=origin,
        source_kind=source_kind,
        source_id=source_id,
        dataset_id=None,
        execution_id_override=idem_exe_id,
        parser=solver.parser,
    )
    payload = wait_for_task(enqueued.task)
    if payload is None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                **enqueued.envelope,
                "message": (
                    "Solve still running after the wait budget — poll poll_url or "
                    "subscribe to ws_url for the result."
                ),
            },
        )
    return apply_solution_filter(
        shape_sync_result(
            payload,
            db=db,
            org_id=org.id,
            execution_id=enqueued.execution_id,
            solver_used=enqueued.effective_solver,
            auto_route_reason=enqueued.auto_route_reason,
            fallback_triggered=enqueued.fallback_triggered,
        ),
        solution_filter,
    )


def _attach_to_inflight_execution(
    *, db: Session, org: Organization, existing: ModelExecution
) -> Any:
    """An idempotent retry raced its in-flight original: wait on THAT task.

    No new enqueue — the retry observes the original solve.
    """
    from celery.result import AsyncResult  # noqa: PLC0415

    from app.shared.core.celery_app import celery_app  # noqa: PLC0415

    task = AsyncResult(existing.celery_task_id, app=celery_app)
    payload = wait_for_task(task)
    if payload is None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "task_id": existing.celery_task_id,
                "execution_id": existing.id,
                "status": "pending",
                "message": (
                    "The original solve for this Idempotency-Key is still running — "
                    "poll poll_url for the result."
                ),
                "ws_url": f"/api/v2/ws/executions/{existing.celery_task_id}",
                "poll_url": f"/api/v2/solve/async/{existing.celery_task_id}",
            },
        )
    return shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=existing.id,
        solver_used=existing.solver_name or DEFAULT_SOLVER_NAME,
        auto_route_reason=existing.auto_route_reason,
        fallback_triggered=False,
    )


@router.post("/validate", response_model=ProblemValidationResponse, operation_id="validate_problem")
def validate_problem_endpoint(  # sync ON PURPOSE -> threadpool (CPU-bound, no awaits)
    problem: OptimizationProblem,
    request: Request,
) -> ProblemValidationResponse:
    """Validate an optimization problem without solving it."""
    errors: list[str] = []
    try:
        validate_problem(problem)
    except HTTPException as e:
        errors.append(str(e.detail))
    except Exception as e:
        errors.append(str(e))

    # Honor the ValidationResult contract the frontend types declare: `errors` and
    # `warnings` are ALWAYS present arrays. Omitting `warnings` here crashed the JSON
    # editor lens, which reads `validation.warnings.length` on every validated edit.
    if errors:
        return ProblemValidationResponse(valid=False, errors=errors, warnings=[])

    return ProblemValidationResponse(
        valid=True,
        errors=[],
        warnings=[],
        num_variables=len(problem.variables),
        num_constraints=len(problem.constraints),
        variable_types={
            "continuous": sum(1 for v in problem.variables if v.type.value == "continuous"),
            "integer": sum(1 for v in problem.variables if v.type.value == "integer"),
            "binary": sum(1 for v in problem.variables if v.type.value == "binary"),
        },
    )


@router.post(
    "/{execution_id}/infeasibility-analysis",
    response_model=InfeasibilityAnalysis,
    operation_id="analyze_infeasibility",
)
def analyze_infeasibility(
    execution_id: str,
    request: Request,
    db: DBSession,
    solver: SolverService = Depends(get_solver_service),
) -> InfeasibilityAnalysis:
    """Compute a minimal conflicting set (IIS) for an INFEASIBLE execution.

    On-demand and org-scoped: the deletion-filtering cost (O(n) re-solves) is paid
    only when the user explicitly asks, never on every infeasible solve. Loads the
    persisted execution, reconstructs the problem from ``input_data``, runs bounded
    IIS (capped by ``IIS_MAX_CONSTRAINTS`` / ``IIS_TIME_BUDGET_SECONDS``), persists
    the result into ``result_data.infeasibility_analysis``, and returns it. When the
    model is too large or the budget is exceeded the analysis comes back as
    ``method="llm_only"`` so the UI can flag heuristic reasoning.

    Defined as a sync handler so the blocking solve loop runs in FastAPI's threadpool.
    """
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    enforce_org_rate_limit(db, org)

    # Load + enforce org ownership (404 hides the existence of other orgs' executions).
    execution = execution_or_404(db, execution_id, org.id)

    result_data = execution.result_data or {}
    if result_data.get("solver_status") != SolverStatus.INFEASIBLE.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Infeasibility analysis only applies to INFEASIBLE executions.",
        )

    # Return the cached analysis if it was already computed for this execution.
    cached = result_data.get("infeasibility_analysis")
    if cached:
        return InfeasibilityAnalysis.model_validate(cached)

    # Reconstruct the problem. input_data is OptimizationProblem.model_dump(mode="json")
    # plus internal underscore-prefixed markers (auto-route reason),
    # which Pydantic ignores. A malformed/legacy payload yields a clean 422.
    try:
        problem = OptimizationProblem.model_validate(execution.input_data or {})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot reconstruct the problem from this execution.",
        ) from exc

    from app.domains.solver.services import compute_iis  # noqa: PLC0415

    # Re-solve with the concrete solver that actually ran (never "auto").
    effective_solver = execution.solver_name
    if effective_solver in (None, "auto"):
        effective_solver = None

    analysis = compute_iis(
        problem,
        solver,
        max_constraints=PSS.get_int(db, "IIS_MAX_CONSTRAINTS"),
        time_budget_s=float(PSS.get_int(db, "IIS_TIME_BUDGET_SECONDS")),
        solver_name=effective_solver,
    )

    # Persist into result_data. Reassign the whole dict so SQLAlchemy detects the
    # change on the JSON column (in-place mutation would not be tracked).
    execution.result_data = {**result_data, "infeasibility_analysis": analysis.model_dump()}
    try:
        db.commit()
    except Exception:
        logger.warning(
            "Failed to persist infeasibility analysis for %s", execution_id, exc_info=True
        )
        db.rollback()

    return analysis


@router.post(
    "/multi-objective",
    response_model=MultiObjectiveResult,
    operation_id="solve_multi_objective",
    dependencies=[Depends(solve_maintenance_gate)],
)
def solve_multi_objective_endpoint(  # def: blocks on the queued result in the threadpool (S4b)
    body: MultiObjectiveSolveRequest,
    request: Request,
    db: DBSession,
    workspace_member: OptionalRequireSolver = None,
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
) -> Any:
    """Solve a multi-objective problem. Returns a Pareto front.

    ADR-007 S4b — async-under-the-hood: the SCIP scalarization loop runs in the
    dedicated ``solve_multi_objective_async`` worker (a durable execution record);
    the handler waits in the threadpool and returns the classic
    ``MultiObjectiveResult``, degrading to 202 + the task envelope past the wait
    budget.
    """
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    enforce_org_rate_limit(db, org)

    enqueued = _enqueue_multi_objective_async(
        db=db,
        org=org,
        user=getattr(request.state, "user", None),
        problem=body.problem,
        config=body.config,
        workspace_id=workspace_member.workspace_id if workspace_member else None,
        origin=origin,
        source_kind=source_kind,
        source_id=source_id,
    )
    payload = wait_for_task(enqueued.task)
    if payload is None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                **enqueued.envelope,
                "message": (
                    "Multi-objective solve still running after the wait budget — poll "
                    "poll_url or subscribe to ws_url for the result."
                ),
            },
        )
    return _shape_multi_objective_result(payload)


@router.post(
    "/async",
    # Two shapes by design (ADR-007 §4): the queue acknowledgement, or — with
    # `wait=true` inside the budget — the exact synchronous result contract.
    response_model=AsyncSolveEnvelope | OptimizationResult,
    dependencies=[Depends(solve_maintenance_gate)],
)
def solve_optimization_problem_async(  # sync ON PURPOSE -> FastAPI threadpool
    # This handler awaits nothing and does real CPU work (tier caps, auto-routing,
    # 27MB model_dump for Celery). As `async def` all of it ran ON the event loop:
    # a burst of big scenario launches froze every other request incl. /health
    # (api flapped "unhealthy", UI looked dead — live 2026-07-04).
    problem: OptimizationProblem,
    request: Request,
    response: Response,
    db: DBSession,
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
    dataset_id: str | None = Query(default=None, max_length=64),
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    """Queue an async solve on the ONE pipeline.

    ``dataset_id`` (§8 Scenarios / S1) records which named dataset the model was
    compiled against — provenance only, the problem body is already grounded.

    ``wait=true`` (ADR-007 §4) blocks in the threadpool for up to
    ``ASYNC_WAIT_TIMEOUT_SECONDS`` and returns the exact synchronous
    ``OptimizationResult`` contract; past the budget it degrades to
    202 + the normal task envelope.
    """
    org: Organization | None = getattr(request.state, "organization", None)
    user = getattr(request.state, "user", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    enforce_org_rate_limit(db, org)

    enqueued = enqueue_async_solve(
        db=db,
        org=org,
        user=user,
        problem=problem,
        workspace_id=workspace_member.workspace_id if workspace_member else None,
        solver_name_param=solver_name,
        origin=origin,
        source_kind=source_kind,
        source_id=source_id,
        dataset_id=dataset_id,
    )
    if not wait:
        return enqueued.envelope

    payload = wait_for_task(enqueued.task)
    if payload is None:
        # Degrade to the plain async envelope: the solve keeps running, the
        # caller polls/reconnects like any async client (ADR-007 §4).
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            **enqueued.envelope,
            "message": (
                "Solve still running after the wait budget — poll poll_url or "
                "subscribe to ws_url for the result."
            ),
        }
    return shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=enqueued.execution_id,
        solver_used=enqueued.effective_solver,
        auto_route_reason=enqueued.auto_route_reason,
        fallback_triggered=enqueued.fallback_triggered,
    )


def _shape_multi_objective_result(
    payload: dict[str, Any] | BaseException,
) -> dict[str, Any]:
    """Map the worker envelope to the sync ``MultiObjectiveResult`` contract (S4b).

    Multi-objective has no error result shape (a Pareto front, not a status), so a
    worker error / crash surfaces as HTTP 422. An empty front (infeasible) rides
    the success envelope unchanged, matching the synchronous contract.
    """
    if isinstance(payload, BaseException):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Multi-objective solve failed: {payload}",
        )
    if payload.get("status") != "success":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(payload.get("error") or "Multi-objective solve failed"),
        )
    result = MultiObjectiveResult(**payload["result"])
    return result.model_dump(mode="json")


@router.get("/async/{task_id}", response_model=AsyncSolveStatusResponse)
def get_async_solve_status(
    task_id: str,
    request: Request,
    db: DBSession,
) -> dict[str, Any]:
    """Get the status of an async solve task."""
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    # Verify task belongs to this organization
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.celery_task_id == task_id,
            ModelExecution.organization_id == org.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    from celery.result import AsyncResult

    from app.shared.core.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    if result.state == "PENDING":
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "Task is waiting to be processed",
        }
    if result.state == "PROGRESS":
        # task_id/status LAST: the task's progress meta carries its own
        # "status" ("completed" for the final "Model found!" tick, still under
        # Celery state PROGRESS) — spreading it after ours let it overwrite
        # "running", and clients then read a "completed" payload with no result
        # and surfaced a false "Solve failed"
        info = result.info if isinstance(result.info, dict) else {}
        return {**info, "task_id": task_id, "status": "running"}
    if result.state == "SUCCESS":
        # The task caught all exceptions and returned a dict.  Check for
        # error conditions at two levels:
        # 1. Task-level: {"status": "error", "error": "..."} — exception handler
        # 2. Solver-level: {"status": "success", "result": {"status": "error"}}
        inner = result.result
        if isinstance(inner, dict):
            # D-13 / INT-01: hoist auto-route telemetry (solver_used,
            # auto_route_reason, warning) from the Celery result dict to the top-level
            # response body in ALL branches — error and success — so callers get
            # consistent access to routing metadata regardless of outcome.
            _telemetry_keys = ("solver_used", "auto_route_reason", "warning")

            # Task-level error (exception caught by solve_async)
            if inner.get("status") == "error":
                error_payload: dict[str, Any] = {
                    "task_id": task_id,
                    "status": "failed",
                    "error": inner.get("error", "Unknown solver error"),
                    "result": inner,
                }
                for key in _telemetry_keys:
                    if key in inner:
                        error_payload[key] = inner[key]
                return error_payload
            # Solver-level error (solver returned error status)
            solver_result = inner.get("result")
            if isinstance(solver_result, dict):
                solver_status = str(solver_result.get("status", "")).lower()
                if solver_status == "error":
                    solver_error_payload: dict[str, Any] = {
                        "task_id": task_id,
                        "status": "failed",
                        "error": solver_result.get("error_message", "Solver returned error"),
                        "result": inner,
                    }
                    for key in _telemetry_keys:
                        if key in inner:
                            solver_error_payload[key] = inner[key]
                    return solver_error_payload
        # D-13 / INT-01: hoist auto-route telemetry to top level
        # for sync-path parity. The Celery task stores solver_used,
        # auto_route_reason, and warning at the top level of the result dict.
        completed_payload: dict[str, Any] = {
            "task_id": task_id,
            "status": "completed",
            "result": inner,
        }
        for key in ("solver_used", "auto_route_reason", "warning"):
            if key in inner:
                completed_payload[key] = inner[key]
        return completed_payload
    if result.state == "FAILURE":
        return {"task_id": task_id, "status": "failed", "error": str(result.result)}
    return {"task_id": task_id, "status": result.state.lower()}


@router.post("/async/{task_id}/cancel", response_model=AsyncSolveCancelResponse)
def cancel_async_task(
    task_id: str,
    request: Request,
    db: DBSession,
) -> AsyncSolveCancelResponse:
    """Cancel a running async optimization task."""
    from app.shared.core.celery_app import celery_app

    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    execution = (
        db.query(ModelExecution)
        .filter(ModelExecution.celery_task_id == task_id, ModelExecution.organization_id == org.id)
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": "Task does not belong to your organization"},
        )

    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    if result.state in ["SUCCESS", "FAILURE"]:
        return AsyncSolveCancelResponse(
            task_id=task_id,
            cancelled=False,
            message=f"Task already {result.state.lower()}, cannot cancel",
        )

    # Mark the execution cancelled BEFORE revoking the Celery task so the
    # worker's SIGTERM handler (the except block in solve_tasks.solve_async)
    # sees the terminal row and treats the user cancellation as such, not as
    # a solver failure. Locked re-read first (S6b): an unlocked stale RUNNING
    # here would clobber a COMPLETED the worker just committed.
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
    return AsyncSolveCancelResponse(
        task_id=task_id, cancelled=True, message="Task cancellation requested"
    )
