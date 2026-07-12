"""Universal Solve Endpoint -- thin route wrappers over the ONE async pipeline (ADR-007)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import OptionalRequireSolver
from app.api.v2.deps.solve_maintenance_gate import solve_maintenance_gate
from app.domains.solver import execution_writer
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
)
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.time_limits import compute_celery_time_limits
from app.models import ModelExecution, ModelProject, Organization
from app.schemas.optimization import (
    InfeasibilityAnalysis,
    MultiObjectiveConfig,
    MultiObjectiveResult,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
)
from app.schemas.tier import tier_cap_detail
from app.services.idempotency import idempotency_execution_id
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.services.solve_orchestrator import (
    ExecutionSource,
    validate_problem,
)
from app.shared.core.prometheus_metrics import SOLVER_AUTO_ROUTE_DECISIONS
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db

logger = logging.getLogger(__name__)

#: ADR-007 §4: server-side wait budget for `POST /solve/async?wait=true`. Kept below
#: the frontend proxy's 120s timeout so a long solve degrades to a clean
#: 202 + task_id instead of an opaque proxy 500.
ASYNC_WAIT_TIMEOUT_SECONDS = 100


def _clamp_time_limit_to_plan(
    problem: OptimizationProblem,
    plan_max_seconds: float,
) -> OptimizationProblem:
    """Return a new OptimizationProblem with options.time_limit_seconds clamped.

    If the input already satisfies the limit, returns the input unchanged.
    Otherwise returns a new instance via nested `model_copy(update=...)` —
    the original `problem` and `problem.options` are guaranteed untouched
    per the project immutability rule.
    """
    if problem.options.time_limit_seconds <= plan_max_seconds:
        return problem
    return problem.model_copy(
        update={
            "options": problem.options.model_copy(update={"time_limit_seconds": plan_max_seconds})
        }
    )


def _enforce_tier_caps(
    db: Session,
    org: Organization,
    problem: OptimizationProblem,
) -> OptimizationProblem:
    """Check tier caps and reject if exceeded. Return problem with time_limit clamped."""
    plan_config = PSS.get_plan_config_dynamic(db, org.plan)

    num_vars = len(problem.variables)
    if num_vars > plan_config["max_variables"]:
        upgrade_map = {"free": "Starter", "starter": "Pro", "pro": "Business"}
        # Dynamically look up the next tier's limit instead of hard-coding
        tier_order = ["free", "starter", "pro", "business"]
        current_idx = tier_order.index(org.plan) if org.plan in tier_order else 0
        if current_idx < len(tier_order) - 1:
            next_tier = tier_order[current_idx + 1]
            next_config = PSS.get_plan_config_dynamic(db, next_tier)
            next_limit_str = f"{next_config['max_variables']:,}"
        else:
            next_limit_str = "unlimited"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="variable_limit_exceeded",
                message=(
                    f"This model has {num_vars:,} variables. "
                    f"Your {org.plan.capitalize()} plan supports up to "
                    f"{plan_config['max_variables']:,}. "
                    f"Upgrade to {upgrade_map.get(org.plan, 'Business')} "
                    f"for up to {next_limit_str} variables."
                ),
                current_plan=org.plan,
                limit=plan_config["max_variables"],
                current_value=num_vars,
            ),
        )

    problem = _clamp_time_limit_to_plan(problem, plan_config["max_solve_time_seconds"])

    allowed, _rate_info = check_rate_limit(
        f"solve_daily:{org.id}",
        plan_config["max_daily_solves"],
        plan_config["max_daily_solves"],
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="daily_solve_quota_exceeded",
                message=(
                    f"You've reached the daily rate limit of "
                    f"{plan_config['max_daily_solves']:,} solves. "
                    f"This limit resets daily. Need more? Upgrade your plan."
                ),
                current_plan=org.plan,
                limit=plan_config["max_daily_solves"],
            ),
        )

    return problem


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
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
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

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

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
                return _attach_to_inflight_execution(db=db, org=org, existing=existing)
            rd = existing.result_data or {}
            # Default to ERROR on missing status: a cached execution with no
            # solver_status in result_data is by definition incomplete (the
            # task crashed before persisting), and returning a fake "optimal"
            # would mask the failure on retry.
            return OptimizationResult(
                status=SolverStatus(rd.get("solver_status", SolverStatus.ERROR.value)),
                objective_value=rd.get("objective_value"),
                solution=rd.get("model"),
                solve_time_seconds=rd.get("solve_time_seconds", 0.0),
                gap=rd.get("gap"),
                error_message=existing.error_message,
                execution_id=existing.id,
            )

    enqueued = _enqueue_async_solve(
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
    payload = _wait_for_task(enqueued.task)
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
    return _shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=enqueued.execution_id,
        solver_used=enqueued.effective_solver,
        auto_route_reason=enqueued.auto_route_reason,
        fallback_triggered=enqueued.fallback_triggered,
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
    payload = _wait_for_task(task)
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
    return _shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=existing.id,
        solver_used=existing.solver_name or DEFAULT_SOLVER_NAME,
        auto_route_reason=existing.auto_route_reason,
        fallback_triggered=False,
    )


@router.post("/validate", operation_id="validate_problem")
def validate_problem_endpoint(  # sync ON PURPOSE -> threadpool (CPU-bound, no awaits)
    problem: OptimizationProblem,
    request: Request,
) -> dict[str, Any]:
    """Validate an optimization problem without solving it."""
    errors: list[Any] = []
    try:
        validate_problem(problem)
    except HTTPException as e:
        errors.append(e.detail)
    except Exception as e:
        errors.append(str(e))

    if errors:
        return {"valid": False, "errors": errors}

    return {
        "valid": True,
        "num_variables": len(problem.variables),
        "num_constraints": len(problem.constraints),
        "variable_types": {
            "continuous": sum(1 for v in problem.variables if v.type.value == "continuous"),
            "integer": sum(1 for v in problem.variables if v.type.value == "integer"),
            "binary": sum(1 for v in problem.variables if v.type.value == "binary"),
        },
    }


@router.post(
    "/{execution_id}/infeasibility-analysis",
    response_model=InfeasibilityAnalysis,
    operation_id="analyze_infeasibility",
)
def analyze_infeasibility(
    execution_id: str,
    request: Request,
    db: Session = Depends(get_db),
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

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    # Load + enforce org ownership (404 hides the existence of other orgs' executions).
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == org.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found",
        )

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
)
def solve_multi_objective_endpoint(  # def: blocks on the queued result in the threadpool (S4b)
    body: MultiObjectiveSolveRequest,
    request: Request,
    db: Session = Depends(get_db),
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

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

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
    payload = _wait_for_task(enqueued.task)
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


class _EnqueuedSolve:
    """Handle for a solve queued through the ONE async pipeline (ADR-007)."""

    __slots__ = (
        "task",
        "execution_id",
        "effective_solver",
        "auto_route_reason",
        "fallback_triggered",
        "envelope",
    )

    def __init__(
        self,
        *,
        task: Any,
        execution_id: str,
        effective_solver: str,
        auto_route_reason: str | None,
        fallback_triggered: bool,
        envelope: dict[str, Any],
    ) -> None:
        self.task = task
        self.execution_id = execution_id
        self.effective_solver = effective_solver
        self.auto_route_reason = auto_route_reason
        self.fallback_triggered = fallback_triggered
        self.envelope = envelope


@router.post("/async", dependencies=[Depends(solve_maintenance_gate)])
def solve_optimization_problem_async(  # sync ON PURPOSE -> FastAPI threadpool
    # This handler awaits nothing and does real CPU work (tier caps, auto-routing,
    # 27MB model_dump for Celery). As `async def` all of it ran ON the event loop:
    # a burst of big scenario launches froze every other request incl. /health
    # (api flapped "unhealthy", UI looked dead — live 2026-07-04).
    problem: OptimizationProblem,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
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

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    enqueued = _enqueue_async_solve(
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

    payload = _wait_for_task(enqueued.task)
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
    return _shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=enqueued.execution_id,
        solver_used=enqueued.effective_solver,
        auto_route_reason=enqueued.auto_route_reason,
        fallback_triggered=enqueued.fallback_triggered,
    )


def _log_solve_analytics(
    db: Session, org: Organization, user: Any, problem: OptimizationProblem
) -> None:
    """Fire-and-forget SOLVER_SOLVE analytics for every async solve.

    ADR-007 S6: restores the signal the deleted sync orchestrator used to emit, now
    uniform across ALL solve entry points (they all funnel through the two enqueue
    helpers). No request context at the enqueue layer, so ``ip_address`` is None —
    geo is the only thing lost versus the old sync emission.
    """
    try:
        from app.services.analytics_service import AnalyticsService  # noqa: PLC0415
        from app.shared.constants import event_types as evt  # noqa: PLC0415

        AnalyticsService(db).log_event(
            user_id=getattr(user, "id", "anonymous"),
            org_id=org.id,
            event_type=evt.SOLVER_SOLVE,
            ip_address=None,
            metadata={
                "num_variables": len(problem.variables),
                "num_constraints": len(problem.constraints),
            },
        )
    except Exception:
        logger.debug("Failed to log SOLVER_SOLVE analytics event", exc_info=True)


def _mark_enqueue_failed(db: Session, execution: ModelExecution, error: str) -> None:
    """Mark an already-committed pending row FAILED after a broker enqueue error.

    P1.5 F0 (insert-before-enqueue): the pending row is committed before
    ``apply_async``, so a broker failure would otherwise leave a 'pending' zombie
    until the reaper. Marking it failed here keeps history truthful immediately.
    """
    try:
        if execution_writer.apply_failed(execution, error=error):
            db.commit()
    except Exception:
        logger.warning("Failed to mark enqueue-failed row %s", execution.id, exc_info=True)
        db.rollback()


def _enqueue_async_solve(
    *,
    db: Session,
    org: Organization,
    user: Any,
    problem: OptimizationProblem,
    workspace_id: str | None,
    solver_name_param: str | None,
    origin: str | None,
    source_kind: str | None,
    source_id: str | None,
    dataset_id: str | None,
    model_project_version_id: str | None = None,
    execution_id_override: str | None = None,
    parser: Any = None,
) -> _EnqueuedSolve:
    """The ONE enqueue path every solve rides (ADR-007): tier caps, provenance,
    auto-routing, queue routing, Celery time limits, the
    pending ``ModelExecution`` row, and the task envelope.

    ``execution_id_override`` binds the row to an idempotency-derived id so a
    retry with the same ``Idempotency-Key`` finds it (the wrapped ``POST /solve``).
    """
    from app.domains.solver.tasks.solve_tasks import solve_async
    from app.shared.utils.id_generator import generate_id

    problem = _enforce_tier_caps(db, org, problem)

    ws_id = workspace_id
    execution_id = execution_id_override or generate_id("exe_")

    # Provenance is sanitized up front: it scopes the dataset lookup below, and
    # the execution INSERT at the end reuses these values.
    async_source = ExecutionSource.from_request(origin, source_kind, source_id)
    # Only mirror the id onto the TYPED project column when it names a real project in
    # this org — source_id is client-supplied, and the typed column feeds joins/reconcile
    # (§14) + P1.5, which must never carry a cross-org or dangling id. The generic
    # source_kind/source_id provenance stays as sanitized above.
    typed_model_project_id: str | None = None
    if async_source.source_kind == "model_project" and async_source.source_id:
        owns_project = (
            db.query(ModelProject.id)
            .filter(
                ModelProject.id == async_source.source_id,
                ModelProject.organization_id == org.id,
            )
            .first()
        )
        if owns_project:
            typed_model_project_id = async_source.source_id

    # §8 Scenarios / S1: dataset provenance. Resolved BEFORE the task is enqueued
    # so an unknown/foreign dataset 404s up front. Org-scoped (and pinned to the
    # project when the solve names one) — a client-supplied id must never resolve
    # across orgs.
    dataset_name: str | None = None
    if dataset_id is not None:
        # Inline org-scoped lookup mirroring model_project_service.get_dataset_or_404 —
        # importing that service here would let the solver-domain routes that import
        # this module reach app.domains.dsl transitively, breaching the
        # domains-independent import contract.
        from app.models.model_project import ModelProjectDataset  # noqa: PLC0415

        ds_query = db.query(ModelProjectDataset).filter(
            ModelProjectDataset.id == dataset_id,
            ModelProjectDataset.organization_id == org.id,
        )
        if typed_model_project_id is not None:
            ds_query = ds_query.filter(
                ModelProjectDataset.model_project_id == typed_model_project_id
            )
        dataset = ds_query.first()
        if dataset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        dataset_name = dataset.name

    # Resolve "auto" to a concrete solver BEFORE enqueuing.
    # D-11 / D-13: uses worker-health probe instead
    # of BYOL license-state DB query.
    requested_async_solver = problem.solver_name or solver_name_param
    async_auto_reason: str | None = None
    async_fallback_triggered: bool = False
    if requested_async_solver == "auto":
        from app.domains.solver.services.auto_router import select_solver  # noqa: PLC0415
        from app.domains.solver.services.solver_service import (  # noqa: PLC0415
            get_solver_service as _get_svc,
        )

        async_effective, async_auto_reason, async_fallback_triggered = select_solver(
            problem, parser if parser is not None else _get_svc().parser
        )
        # D-13: structured log + counter on async path.
        logger.info(
            "auto_route_decision",
            extra={
                "solver_used": async_effective,
                "auto_route_reason": async_auto_reason,
                "execution_id": execution_id,
                "organization_id": org.id,
                "fallback_triggered": async_fallback_triggered,
            },
        )
        SOLVER_AUTO_ROUTE_DECISIONS.labels(
            solver_used=async_effective, reason=async_auto_reason
        ).inc()
    else:
        async_effective = requested_async_solver

    effective_async_solver = async_effective or DEFAULT_SOLVER_NAME

    # D-11 / WR-04: direct hexaly + worker down → 503 up front.
    # The auto-router resolved "auto" → effective_async_solver above; if the router
    # chose hexaly_unavailable_fallback (SCIP) the gate must NOT fire — only direct
    # hexaly selection should 503.
    if not async_fallback_triggered:
        ensure_hexaly_worker_or_503(effective_async_solver)

    # Validate BEFORE enqueuing: a parseable-but-semantically-invalid problem
    # (undefined var refs, inverted bounds) raises HTTP 400 here — never reaches
    # the worker.
    validate_problem(problem)

    problem_data = problem.model_dump(mode="json")
    # Phase 7.4: use the post-auto-routing effective solver (computed above).
    # Thread the auto-route reason + fallback flag through to the worker for
    # result-dict construction (D-13 async parity).
    effective_solver_name = async_effective
    if async_auto_reason is not None:
        problem_data["_auto_route_reason"] = async_auto_reason
    if async_fallback_triggered:
        problem_data["_fallback_triggered"] = True

    # An unknown solver name rejects the submission before anything is queued.
    try:
        target_queue = resolve_queue(effective_solver_name)
    except SolverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # W15/F-01: worker-level kill switch. Solver-internal limits stop
    # well-behaved solves; a C-level hang survives them. Derive Celery
    # soft/hard time limits from the request's own solver time limit so a
    # hung worker child is killed, the refund fires, and the slot frees up.
    soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)

    # P1.5 F0 (ADR-007 debt) — insert the pending row BEFORE enqueuing so a
    # broker-accepted task can never briefly exist with no history row: the reaper
    # reconciles a crashed worker BY its row, and the idempotent-retry attach path
    # (S2) needs the row present from enqueue time. ``solve_async`` keys its terminal
    # write off ``celery_task_id``, so the id is generated here and passed to
    # ``apply_async(task_id=...)`` — the row and the task share it from birth (the
    # execute_model insert-first pattern keys off execution_id instead, so it never
    # needed this).
    celery_task_id = str(uuid4())

    # Minimal execution record so /async/{task_id} can verify ownership (prevents IDOR).
    # Provenance (async_source / typed_model_project_id / dataset) was resolved and
    # validated up front. ADR-007 S3: the ONE writer owns
    # the row so the insert shape stays identical across every enqueue site.
    execution = execution_writer.insert_pending(
        db,
        execution_id=execution_id,
        organization_id=org.id,
        celery_task_id=celery_task_id,
        input_data=problem_data,
        solver_name=effective_solver_name or DEFAULT_SOLVER_NAME,
        executed_by_user_id=user.id if user else None,
        # D-13: persist auto-routing slug at enqueue time (Plan 09 migration column).
        auto_route_reason=async_auto_reason,
        origin=async_source.origin,
        source_kind=async_source.source_kind,
        source_id=async_source.source_id,
        # Typed per-project column for fast per-project history + the §14 durable
        # reconcile + P1.5 — populated only when validated as an in-org project above.
        model_project_id=typed_model_project_id,
        # Version provenance rides ONLY alongside a validated in-org project id so a
        # client can never stamp a dangling version id (S4a: project-solve passes it).
        model_project_version_id=(
            model_project_version_id if typed_model_project_id is not None else None
        ),
        # §8/S1: dataset provenance — name is a snapshot so history survives
        # dataset deletion. Both None unless the id resolved in-org above.
        dataset_id=dataset_id,
        dataset_name=dataset_name,
    )
    pending_committed = False
    try:
        db.commit()
        pending_committed = True
    except Exception:
        # Best-effort (mirrors the historic behavior): a duplicate id from a racing
        # idempotent retry, or a transient DB error, must not fail an otherwise-valid
        # solve — the racer's row (or the reaper) still tracks it and the caller still
        # gets the result from the task itself.
        logger.warning(
            "Failed to commit pending ModelExecution %s before enqueue",
            execution_id,
            exc_info=True,
        )
        db.rollback()

    # WR-07: if the broker is unreachable, apply_async raises and the client
    # sees a clean 503 with nothing queued (bar the pending row, marked failed below).
    try:
        task = solve_async.apply_async(
            kwargs={
                "problem_data": problem_data,
                "organization_id": org.id,
                "user_id": user.id if user else None,
                "workspace_id": ws_id,
                "warm_start_execution_id": (
                    problem.warm_start.execution_id if problem.warm_start else None
                ),
                "solver_name": effective_solver_name,
            },
            task_id=celery_task_id,
            queue=target_queue,
            soft_time_limit=soft_limit,
            time_limit=hard_limit,
        )
    except Exception as exc:
        logger.error("apply_async failed for solve %s: %s", execution_id, exc)
        if pending_committed:
            _mark_enqueue_failed(db, execution, f"Failed to enqueue task: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue solve task. Please retry shortly.",
            },
        ) from exc

    _log_solve_analytics(db, org, user, problem)

    task_envelope = {
        # P1.5 F0: report the id we pre-generated and submitted (celery honors
        # task_id=), so the envelope, the pending row's celery_task_id, and the id
        # the worker runs under are the SAME by construction.
        "task_id": celery_task_id,
        # ADR-007 §6: the ModelExecution row id is first-class in the async contract
        # (additive) — task_id keys Celery/WS, execution_id keys history.
        "execution_id": execution_id,
        "status": "pending",
        "message": "Task queued for processing",
        "ws_url": f"/api/v2/ws/executions/{celery_task_id}",
        "poll_url": f"/api/v2/solve/async/{celery_task_id}",
    }
    return _EnqueuedSolve(
        task=task,
        execution_id=execution_id,
        effective_solver=effective_async_solver,
        auto_route_reason=async_auto_reason,
        fallback_triggered=async_fallback_triggered,
        envelope=task_envelope,
    )


def _enqueue_multi_objective_async(
    *,
    db: Session,
    org: Organization,
    user: Any,
    problem: OptimizationProblem,
    config: MultiObjectiveConfig,
    workspace_id: str | None,
    origin: str | None,
    source_kind: str | None,
    source_id: str | None,
) -> _EnqueuedSolve:
    """Enqueue a multi-objective solve (ADR-007 S4b).

    Multi-objective can't ride ``_enqueue_async_solve`` (that hardcodes the
    single-solve task + auto-routing). It always runs SCIP scalarization (no
    routing) and dispatches the dedicated ``solve_multi_objective_async`` task.
    Same pending-row + queue time-limit discipline as the single-solve path.
    """
    from app.domains.solver.tasks.solve_tasks import solve_multi_objective_async
    from app.shared.utils.id_generator import generate_id

    problem = _enforce_tier_caps(db, org, problem)
    execution_id = generate_id("exe_")

    # Provenance up front (sanitized) — mirrors the single-solve enqueue; the typed
    # project column is only set when source_id names a real in-org project.
    mo_source = ExecutionSource.from_request(origin, source_kind, source_id)
    typed_model_project_id: str | None = None
    if mo_source.source_kind == "model_project" and mo_source.source_id:
        owns_project = (
            db.query(ModelProject.id)
            .filter(
                ModelProject.id == mo_source.source_id,
                ModelProject.organization_id == org.id,
            )
            .first()
        )
        if owns_project:
            typed_model_project_id = mo_source.source_id

    # Validate BEFORE enqueuing (parity with the single-solve enqueue).
    validate_problem(problem)

    problem_data = problem.model_dump(mode="json")
    config_data = config.model_dump(mode="json")

    soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)
    target_queue = resolve_queue("scip")

    # P1.5 F0 (ADR-007 debt): insert-before-enqueue with a pre-generated task id — same
    # rationale as the single-solve enqueue (the worker keys off ``celery_task_id``).
    celery_task_id = str(uuid4())

    execution = execution_writer.insert_pending(
        db,
        execution_id=execution_id,
        organization_id=org.id,
        celery_task_id=celery_task_id,
        input_data=problem_data,
        solver_name="scip",
        executed_by_user_id=user.id if user else None,
        origin=mo_source.origin,
        source_kind=mo_source.source_kind,
        source_id=mo_source.source_id,
        model_project_id=typed_model_project_id,
    )
    pending_committed = False
    try:
        db.commit()
        pending_committed = True
    except Exception:
        logger.warning(
            "Failed to commit pending ModelExecution %s before multi-objective enqueue",
            execution_id,
            exc_info=True,
        )
        db.rollback()

    try:
        task = solve_multi_objective_async.apply_async(
            kwargs={
                "problem_data": problem_data,
                "config_data": config_data,
                "organization_id": org.id,
                "user_id": user.id if user else None,
                "workspace_id": workspace_id,
            },
            task_id=celery_task_id,
            queue=target_queue,
            soft_time_limit=soft_limit,
            time_limit=hard_limit,
        )
    except Exception as exc:
        logger.error("apply_async failed for multi-objective solve %s: %s", execution_id, exc)
        if pending_committed:
            _mark_enqueue_failed(db, execution, f"Failed to enqueue task: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue multi-objective solve. Please retry shortly.",
            },
        ) from exc

    _log_solve_analytics(db, org, user, problem)

    task_envelope = {
        # P1.5 F0: the pre-generated id (submitted via task_id=) is the single id
        # shared by the envelope, the pending row and the running task.
        "task_id": celery_task_id,
        "execution_id": execution_id,
        "status": "pending",
        "message": "Multi-objective task queued for processing",
        "ws_url": f"/api/v2/ws/executions/{celery_task_id}",
        "poll_url": f"/api/v2/solve/async/{celery_task_id}",
    }
    return _EnqueuedSolve(
        task=task,
        execution_id=execution_id,
        effective_solver="scip",
        auto_route_reason=None,
        fallback_triggered=False,
        envelope=task_envelope,
    )


def _wait_for_task(task: Any) -> dict[str, Any] | BaseException | None:
    """Bounded blocking wait on a queued solve; ``None`` means the budget ran out.

    Runs in the threadpool — every caller is a sync ``def`` handler on purpose;
    a blocking ``get`` must never sit on the event loop. With ``propagate=False``
    a hard task failure comes back as the exception OBJECT, never raises.
    """
    from celery.exceptions import TimeoutError as CeleryTimeoutError  # noqa: PLC0415

    try:
        return task.get(timeout=ASYNC_WAIT_TIMEOUT_SECONDS, propagate=False)
    except CeleryTimeoutError:
        return None


def _shape_sync_result(
    payload: dict[str, Any] | BaseException,
    *,
    db: Session,
    org_id: str,
    execution_id: str,
    solver_used: str,
    auto_route_reason: str | None,
    fallback_triggered: bool,
) -> dict[str, Any]:
    """Map the worker envelope to the SYNC ``OptimizationResult`` contract.

    ADR-007 §4: the caller ran the exact enqueue path (provenance, pending row);
    this helper only reshapes. The worker's ``OptimizationResult`` carries a
    schema default for ``execution_id`` (the sync orchestrator used to inject
    it), so it is injected here.
    """
    if isinstance(payload, BaseException):
        # Task hard-killed or crashed before its own error handling: the reaper
        # reconciles the row; report the sync error shape.
        result = OptimizationResult(
            status=SolverStatus.ERROR,
            solve_time_seconds=0.0,
            error_message=f"Solve task failed: {payload}",
        )
    elif payload.get("status") == "success":
        result = OptimizationResult(**payload["result"])
    else:
        # Task-level error: the worker returned {"status": "error"} (an exception
        # it caught).
        result = OptimizationResult(
            status=SolverStatus.ERROR,
            solve_time_seconds=0.0,
            error_message=str(payload.get("error") or "Solve failed"),
        )

    result.execution_id = execution_id
    envelope = payload if isinstance(payload, dict) else {}
    result.solver_used = envelope.get("solver_used") or solver_used
    result.auto_route_reason = envelope.get("auto_route_reason") or auto_route_reason
    warning = envelope.get("warning")
    if warning is None and fallback_triggered:
        # Same message the sync route surfaces on a Hexaly→SCIP fallback.
        warning = "Hexaly temporarily unavailable; solved with SCIP (quadratic quality may differ)"
    if warning is not None:
        result.warning = warning
    return result.model_dump(mode="json")


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


@router.get("/async/{task_id}")
async def get_async_solve_status(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
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
        return {"task_id": task_id, "status": "running", **result.info}
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


@router.post("/async/{task_id}/cancel")
async def cancel_async_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
        return {
            "task_id": task_id,
            "cancelled": False,
            "message": f"Task already {result.state.lower()}, cannot cancel",
        }

    # Mark the execution cancelled BEFORE revoking the Celery task so the
    # worker's SIGTERM handler (the except block in solve_tasks.solve_async)
    # sees the terminal row and treats the user cancellation as such, not as
    # a solver failure.
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
    return {"task_id": task_id, "cancelled": True, "message": "Task cancellation requested"}
