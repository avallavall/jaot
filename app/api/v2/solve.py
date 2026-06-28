"""Universal Solve Endpoint -- thin route wrappers delegating to SolveOrchestrator."""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import OptionalRequireSolver
from app.api.v2.deps.solve_maintenance_gate import solve_maintenance_gate
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.prepaid import clear_prepaid_credits, set_prepaid_credits
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.services.pool import get_solver_pool
from app.domains.solver.time_limits import compute_celery_time_limits
from app.models import ExecutionStatus, ModelExecution, Organization
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
from app.services.platform_settings_service import (
    MissingSettingError,
    PlatformSettingsService as PSS,
)
from app.services.solve_orchestrator import (
    ExecutionSource,
    SolveOrchestrator,
    load_warm_start_solution,
    validate_problem,
)
from app.shared.core.prometheus_metrics import SOLVER_AUTO_ROUTE_DECISIONS
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


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


def compute_credits(
    num_variables: int,
    num_integer_binary: int,
    num_constraints: int,
    time_limit_seconds: float = 60.0,
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

    # --- time bonus: 1 credit per extra minute beyond 60s ---
    if time_limit_seconds > 60:
        time_cost = math.ceil((time_limit_seconds - 60) / 60)
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
async def solve_optimization_problem(
    problem: OptimizationProblem,
    request: Request,
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
) -> OptimizationResult:
    """Solve an optimization problem (universal endpoint).

    Supports client-side idempotency via the ``Idempotency-Key`` header. A
    retry with the same key returns the previously persisted result without
    re-solving or deducting credits twice.
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
                credits_used=existing.credits_consumed or 0,
                credits_remaining=org.credits_balance,
            )

    problem = _enforce_tier_caps(db, org, problem)

    # Resolve solver_name: problem body takes precedence over query param
    requested_solver_name = problem.solver_name or solver_name

    # Resolve "auto" to a concrete solver BEFORE the orchestrator runs the
    # pre-enqueue gate + credit debit. The reason code is propagated into the
    # response for UI transparency (D-08 / D-13).
    auto_route_reason: str | None = None
    fallback_triggered: bool = False
    if requested_solver_name == "auto":
        from app.domains.solver.services.auto_router import select_solver  # noqa: PLC0415

        effective_solver_name, auto_route_reason, fallback_triggered = select_solver(
            problem, solver.parser
        )
        # D-13: structured log + Prometheus counter per auto-route decision.
        logger.info(
            "auto_route_decision",
            extra={
                "solver_used": effective_solver_name,
                "auto_route_reason": auto_route_reason,
                "execution_id": idem_exe_id or "(pre-solve)",
                "organization_id": org.id,
                "fallback_triggered": fallback_triggered,
            },
        )
        SOLVER_AUTO_ROUTE_DECISIONS.labels(
            solver_used=effective_solver_name, reason=auto_route_reason
        ).inc()
    else:
        effective_solver_name = requested_solver_name

    # D-11 / WR-04: direct hexaly + worker down → 503 BEFORE credit debit.
    # Shared helper enforces D-11 contract uniformly across all four solve entry
    # points (sync solve / async solve / file_io import / template solve).
    ensure_hexaly_worker_or_503(effective_solver_name)

    # PRC-01 / D-02: multiply base credits by PSS-resolved per-
    # solver multiplier AFTER auto-routing. effective_solver_name holds the
    # post-routing concrete solver (not "auto").
    base_credits = calculate_credits(problem, solver_name=effective_solver_name, db=db)
    credits_needed = max(1, round(base_credits * 0.5)) if problem.warm_start else base_credits

    validate_problem(problem)

    ws_id = workspace_member.workspace_id if workspace_member else None
    user = getattr(request.state, "user", None)
    warm_start_solution = (
        load_warm_start_solution(db, problem.warm_start.execution_id, org.id)
        if problem.warm_start
        else None
    )

    orchestrator = SolveOrchestrator(db, solver, get_solver_pool())
    try:
        result = await orchestrator.solve_single(
            problem=problem,
            org=org,
            user=user,
            request=request,
            credits_needed=credits_needed,
            workspace_id=ws_id,
            warm_start_solution=warm_start_solution,
            execution_id=idem_exe_id,
            solver_name=effective_solver_name,
            auto_route_reason=auto_route_reason,
            source=ExecutionSource.from_request(origin, source_kind, source_id),
        )
    except (SolverNotFoundError, SolverUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # D-08 / D-13 transparency: expose effective solver + routing reason.
    result.solver_used = effective_solver_name or DEFAULT_SOLVER_NAME
    result.auto_route_reason = auto_route_reason
    # D-11: surface warning when Hexaly fell back to SCIP.
    if fallback_triggered:
        result.warning = (
            "Hexaly temporarily unavailable; solved with SCIP (quadratic quality may differ)"
        )
    return result


@router.post("/validate", operation_id="validate_problem")
async def validate_problem_endpoint(
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
        # D-02: validate-credits preview intentionally omits solver_name —
        # preview shows base cost without per-solver multiplier (multiplier surfaces
        # at submit time after auto-router decision).
        "estimated_credits": calculate_credits(problem),
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
    # plus internal underscore-prefixed markers (prepaid credits, auto-route reason),
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
async def solve_multi_objective_endpoint(
    body: MultiObjectiveSolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
) -> MultiObjectiveResult:
    """Solve a multi-objective problem. Returns a Pareto front."""
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    problem, config = body.problem, body.config
    problem = _enforce_tier_caps(db, org, problem)

    # D-02: multi-objective uses SCIP scalarization (no auto-routing
    # at this tier — the orchestrator dispatches to SCIP for scalarized subproblems).
    # Hexaly multi-objective is out of scope for this phase.
    total_credits = calculate_credits(problem, solver_name="scip", db=db) * config.n_points

    validate_problem(problem)
    ws_id = workspace_member.workspace_id if workspace_member else None
    user = getattr(request.state, "user", None)

    orchestrator = SolveOrchestrator(db, solver, get_solver_pool())
    return await orchestrator.solve_multi_objective(
        problem=problem,
        config=config,
        org=org,
        user=user,
        request=request,
        total_credits=total_credits,
        workspace_id=ws_id,
        source=ExecutionSource.from_request(origin, source_kind, source_id),
    )


@router.post("/async", dependencies=[Depends(solve_maintenance_gate)])
async def solve_optimization_problem_async(
    problem: OptimizationProblem,
    request: Request,
    db: Session = Depends(get_db),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
    origin: str | None = Query(default=None, max_length=32),
    source_kind: str | None = Query(default=None, max_length=32),
    source_id: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    """Queue an async solve. Pre-pays credits; refund happens in Celery on failure."""
    from app.domains.solver.tasks.solve_tasks import solve_async
    from app.services import workspace_credits_service
    from app.services.credits_service import CreditsService, InsufficientCreditsError
    from app.shared.core.prometheus_metrics import RefundReason
    from app.shared.utils.id_generator import generate_id

    org: Organization | None = getattr(request.state, "organization", None)
    user = getattr(request.state, "user", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    problem = _enforce_tier_caps(db, org, problem)

    ws_id = workspace_member.workspace_id if workspace_member else None
    execution_id = generate_id("exe_")

    # Resolve "auto" to a concrete solver BEFORE pre-paying credits or
    # enqueuing. D-11 / D-13: uses worker-health probe instead
    # of BYOL license-state DB query.
    requested_async_solver = problem.solver_name or solver_name
    async_auto_reason: str | None = None
    async_fallback_triggered: bool = False
    if requested_async_solver == "auto":
        from app.domains.solver.services.auto_router import select_solver  # noqa: PLC0415
        from app.domains.solver.services.solver_service import (  # noqa: PLC0415
            get_solver_service as _get_svc,
        )

        _svc = _get_svc()
        async_effective, async_auto_reason, async_fallback_triggered = select_solver(
            problem, _svc.parser
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

    # D-11 / WR-04: direct hexaly + worker down → 503 BEFORE credit debit.
    # The auto-router resolved "auto" → effective_async_solver above; if the router
    # chose hexaly_unavailable_fallback (SCIP) the gate must NOT fire — only direct
    # hexaly selection should 503.
    if not async_fallback_triggered:
        ensure_hexaly_worker_or_503(effective_async_solver)

    # PRC-01 / D-02: multiply base credits by PSS-resolved per-solver
    # multiplier AFTER auto-routing. async_effective holds the post-routing concrete
    # solver name (not "auto"). effective_async_solver falls back to DEFAULT_SOLVER_NAME
    # when async_effective is None.
    base_credits = calculate_credits(problem, solver_name=effective_async_solver, db=db)
    credits_needed = max(1, round(base_credits * 0.5)) if problem.warm_start else base_credits

    # Pre-pay credits BEFORE queueing (refund happens in Celery on failure)
    prepaid = False
    if ws_id:
        try:
            workspace_credits_service.deduct_credits_for_solve(
                db=db, org=org, workspace_id=ws_id, credits_needed=credits_needed
            )
            db.commit()
            prepaid = True
        except ValueError:
            pass  # Pool exhausted -- fall through to org balance
    if not prepaid:
        try:
            CreditsService.deduct_credits(
                db=db,
                organization_id=org.id,
                credits=credits_needed,
                description=f"Async solve: {execution_id}",
                reference_type="solve",
                reference_id=execution_id,
            )
            db.commit()
        except InsufficientCreditsError as e:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "insufficient_credits",
                    "credits_needed": e.credits_needed,
                    "credits_available": e.credits_available,
                },
            ) from e

    validate_problem(problem)

    problem_data = problem.model_dump(mode="json")
    # Pass the prepaid amount through so the Celery task can refund it on
    # failure (D-19). Without this, solve_tasks.solve_async cannot know how
    # much was pre-paid and silently loses the credits on any exception.
    set_prepaid_credits(problem_data, credits_needed)
    # Phase 7.4: use the post-auto-routing effective solver (computed above).
    # Thread the auto-route reason + fallback flag through to the worker for
    # result-dict construction (D-13 async parity).
    effective_solver_name = async_effective
    if async_auto_reason is not None:
        problem_data["_auto_route_reason"] = async_auto_reason
    if async_fallback_triggered:
        problem_data["_fallback_triggered"] = True

    # Refund pre-paid credits if the solver name is unknown so an invalid
    # submission is not charged.
    try:
        target_queue = resolve_queue(effective_solver_name)
    except SolverNotFoundError as exc:
        try:
            CreditsService(db).refund_credits(
                organization_id=org.id,
                credits=credits_needed,
                description=f"{RefundReason.UNKNOWN_SOLVER.value}: {execution_id}",
                reference_type="solve_routing_error",
                reference_id=execution_id,
            )
            db.commit()
        except Exception:
            logger.warning(
                "Failed to refund prepaid credits after routing rejection for %s",
                execution_id,
                exc_info=True,
            )
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # W15/F-01: worker-level kill switch. Solver-internal limits stop
    # well-behaved solves; a C-level hang survives them. Derive Celery
    # soft/hard time limits from the request's own solver time limit so a
    # hung worker child is killed, the refund fires, and the slot frees up.
    soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)

    # WR-07 symmetry: if the broker is unreachable, apply_async raises and
    # the already-deducted credits must be refunded — otherwise the client
    # sees a 5xx and their balance is silently debited with no task queued.
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
            queue=target_queue,
            soft_time_limit=soft_limit,
            time_limit=hard_limit,
        )
    except Exception as exc:
        logger.error(
            "apply_async failed for solve %s; refunding %d credits: %s",
            execution_id,
            credits_needed,
            exc,
        )
        try:
            CreditsService(db).refund_credits(
                organization_id=org.id,
                credits=credits_needed,
                description=f"{RefundReason.ENQUEUE_FAILED.value}: {execution_id}",
                reference_type="solve",
                reference_id=execution_id,
            )
            db.commit()
        except Exception:
            logger.warning(
                "Failed to refund credits after apply_async failure for %s",
                execution_id,
                exc_info=True,
            )
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue solve task. Please retry shortly.",
            },
        ) from exc

    # Minimal execution record so /async/{task_id} can verify ownership (prevents IDOR).
    async_source = ExecutionSource.from_request(origin, source_kind, source_id)
    pending_exec = ModelExecution(
        id=execution_id,
        organization_id=org.id,
        executed_by_user_id=user.id if user else None,
        celery_task_id=task.id,
        is_async=True,
        status="pending",
        input_data=problem_data,
        created_at=utcnow(),
        solver_name=effective_solver_name or DEFAULT_SOLVER_NAME,
        # D-13: persist auto-routing slug at enqueue time.
        # DB column added by Plan 09 migration.
        auto_route_reason=async_auto_reason,
        origin=async_source.origin,
        source_kind=async_source.source_kind,
        source_id=async_source.source_id,
    )
    db.add(pending_exec)
    try:
        db.commit()
    except Exception:
        logger.warning(
            "Failed to create pending ModelExecution %s for task %s",
            execution_id,
            task.id,
            exc_info=True,
        )
        db.rollback()  # Non-critical: poll will still work via Celery

    return {
        "task_id": task.id,
        "status": "pending",
        "message": "Task queued for processing",
        "ws_url": f"/api/v2/ws/executions/{task.id}",
        "poll_url": f"/api/v2/solve/async/{task.id}",
        "estimated_credits": credits_needed,
    }


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

    # Mark the execution cancelled and strip the _prepaid_credits marker
    # BEFORE revoking the Celery task. The worker's SIGTERM handler enters
    # the except block in solve_tasks.solve_async and would otherwise treat
    # the user cancellation as a solver failure and issue a refund. Policy:
    # a user-triggered cancel does NOT refund automatically (operator can
    # issue a manual refund if appropriate). Using an immutable copy
    # satisfies the project immutability rule.
    cancelled_input = {**(execution.input_data or {})}
    clear_prepaid_credits(cancelled_input)
    execution.input_data = cancelled_input
    execution.status = ExecutionStatus.CANCELLED.value
    execution.error_message = "Cancelled by user"
    execution.completed_at = utcnow()
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
