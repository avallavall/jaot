"""Solve orchestration service.

Coordinates the full solve lifecycle:
  1. Pre-pay credits (deduct BEFORE solving)
  2. Execute solve in ThreadPoolExecutor
  3. Refund credits on failure
  4. Record execution and audit log
  5. Update metrics

This service extracts business logic from the solve route handlers,
keeping routes as thin wrappers. Follows the pre-pay + refund credit
pattern established in llm.py.
"""

import asyncio
import logging
import re
import time as _time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.domains.solver.adapters import DEFAULT_SOLVER_NAME
from app.domains.solver.services import SolverService, get_solver_service
from app.models import ModelExecution, Organization
from app.models.audit_log import AuditAction
from app.schemas.optimization import (
    MultiObjectiveConfig,
    MultiObjectiveResult,
    OptimizationProblem,
    OptimizationResult,
    ParetoPoint,
    SolverStatus,
)
from app.services import workspace_credits_service
from app.services.audit_service import log_action
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.prometheus_metrics import (
    ACTIVE_SOLVES,
    CREDITS_CONSUMED,
    SOLVE_DURATION,
    SOLVE_TOTAL,
    RefundReason,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Variable name tokens excluded from expression parsing
_EXCLUDED_TOKENS = {
    "sin",
    "cos",
    "tan",
    "exp",
    "log",
    "sqrt",
    "abs",
    "min",
    "max",
    "sum",
}


# Standalone validation helpers (importable without instantiating class)


def validate_problem(problem: OptimizationProblem) -> None:
    """Validate optimization problem before solving. Raises HTTPException if invalid."""
    variable_names = {v.name for v in problem.variables}

    obj_vars = extract_variable_names(problem.objective.expression)
    invalid_obj_vars = obj_vars - variable_names
    if invalid_obj_vars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Objective references undefined variables: {invalid_obj_vars}",
        )

    for i, constraint in enumerate(problem.constraints):
        constraint_vars = extract_variable_names(constraint.expression)
        invalid_vars = constraint_vars - variable_names
        if invalid_vars:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Constraint {constraint.name or i} references "
                    f"undefined variables: {invalid_vars}"
                ),
            )

    for var in problem.variables:
        if var.lower_bound is not None and var.upper_bound is not None:
            if var.lower_bound > var.upper_bound:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Variable {var.name} has invalid bounds: "
                        f"{var.lower_bound} > {var.upper_bound}"
                    ),
                )

        if var.type.value == "binary":
            if var.lower_bound is not None and var.lower_bound < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Binary variable {var.name} cannot have lower bound < 0",
                )
            if var.upper_bound is not None and var.upper_bound > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Binary variable {var.name} cannot have upper bound > 1",
                )


def extract_variable_names(expression: str) -> set[str]:
    """Extract variable names from a mathematical expression."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expression)
    return {t for t in tokens if t not in _EXCLUDED_TOKENS}


def load_warm_start_solution(
    db: Session,
    execution_id: str,
    org_id: str,
) -> dict[str, float] | None:
    """Load a warm start solution from a previous execution.

    Returns the solution dict if valid, else None. Never raises.
    """
    try:
        execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
        if not execution:
            logger.warning("Warm start execution not found: %s", execution_id)
            return None
        if execution.organization_id != org_id:
            logger.warning("Warm start execution %s belongs to different org", execution_id)
            return None
        if execution.status not in ("completed",):
            logger.warning(
                "Warm start execution %s not completed (status=%s)",
                execution_id,
                execution.status,
            )
            return None
        if execution.solver_status not in ("optimal", "feasible"):
            logger.warning(
                "Warm start execution %s has no valid solution (solver_status=%s)",
                execution_id,
                execution.solver_status,
            )
            return None
        result_data = execution.result_data or {}
        solution = result_data.get("solution")
        if not solution or not isinstance(solution, dict):
            logger.warning("Warm start execution %s has no solution dict", execution_id)
            return None
        logger.info("Loaded warm start solution from execution %s", execution_id)
        return {k: float(v) for k, v in solution.items()}
    except Exception as e:
        logger.warning("Failed to load warm start solution: %s", e)
        return None


class SolveOrchestrator:
    """Orchestrates the solve flow: pre-pay -> solve -> refund on failure -> audit.

    Usage::

        orchestrator = SolveOrchestrator(db, solver, solver_pool)
        result = await orchestrator.solve_single(problem, org, user, request)
    """

    def __init__(
        self,
        db: Session,
        solver: SolverService,
        solver_pool: ThreadPoolExecutor,
    ) -> None:
        self.db = db
        self.solver = solver
        self.solver_pool = solver_pool

    async def solve_single(
        self,
        problem: OptimizationProblem,
        org: Organization,
        user: object | None,
        request: Request,
        credits_needed: int,
        workspace_id: str | None = None,
        warm_start_solution: dict[str, float] | None = None,
        execution_id: str | None = None,
        solver_name: str | None = None,
        auto_route_reason: str | None = None,
    ) -> OptimizationResult:
        """Full single-objective solve with pre-pay + refund credit pattern.

        If *execution_id* is provided (e.g. derived from an Idempotency-Key),
        it is used as the stable reference for credit transactions and the
        persisted ModelExecution row. Otherwise a fresh id is generated.

        ``auto_route_reason`` is the Phase 7.4 / D-13 slug from the auto-router
        (e.g. ``"quadratic_routed_to_hexaly"``). Passed through to
        :meth:`_persist_sync_execution` for DB persistence.
        """
        if execution_id is None:
            execution_id = generate_id("exe_")
        timeout_seconds = PSS.get_int(self.db, "SOLVER_TIMEOUT_SECONDS")

        # Use requested solver if specified, otherwise fall back to the default solver
        effective_solver = (
            get_solver_service(solver_name=solver_name) if solver_name else self.solver
        )

        start = _time.monotonic()
        result: OptimizationResult = await self._execute_with_credits(
            solve_fn=lambda: effective_solver.solve(
                problem, warm_start_solution=warm_start_solution
            ),
            credits_needed=credits_needed,
            org=org,
            workspace_id=workspace_id,
            execution_id=execution_id,
            request=request,
            generator_label="direct",
            timeout_seconds=timeout_seconds,
        )
        elapsed_ms = int((_time.monotonic() - start) * 1000)

        # Required for the post-import redirect (P5 file import flow) so the
        # executions detail page can find the row right after the response.
        self._persist_sync_execution(
            execution_id=execution_id,
            problem=problem,
            result=result,
            org=org,
            user=user,
            credits_needed=credits_needed,
            elapsed_ms=elapsed_ms,
            solver_name=solver_name,
            auto_route_reason=auto_route_reason,
        )

        # Audit log
        if user:
            log_action(
                db=self.db,
                organization_id=org.id,
                actor=user,
                action=AuditAction.SOLVE,
                target_type="solve",
                target_id=problem.name or "unnamed",
                target_name=problem.name or "optimization_solve",
                metadata={
                    "credits_used": credits_needed,
                    "status": result.status.value,
                },
            )

        updated_org = self.db.query(Organization).filter(Organization.id == org.id).first()

        result.execution_id = execution_id
        result.credits_used = credits_needed
        result.credits_remaining = updated_org.credits_balance if updated_org else 0

        # Fire-and-forget analytics
        self._log_analytics_solve(user, org, request, problem, credits_needed, result)

        return result

    def _persist_sync_execution(
        self,
        execution_id: str,
        problem: OptimizationProblem,
        result: OptimizationResult,
        org: Organization,
        user: object | None,
        credits_needed: int,
        elapsed_ms: int,
        solver_name: str | None = None,
        auto_route_reason: str | None = None,
    ) -> None:
        """Insert a ModelExecution row for a completed synchronous solve.

        DB errors are logged and rolled back — the response still returns the
        OptimizationResult; only the executions detail page is affected.
        """
        try:
            solver_status = result.status.value
            now = utcnow()
            row = ModelExecution(
                id=execution_id,
                organization_id=org.id,
                executed_by_user_id=getattr(user, "id", None),
                input_data=problem.model_dump(mode="json"),
                result_data=result.to_result_data(),
                status="failed" if solver_status == "error" else "completed",
                error_message=result.error_message,
                execution_time_ms=elapsed_ms,
                solver_status=solver_status,
                solver_name=solver_name or DEFAULT_SOLVER_NAME,
                # Phase 7.4 / D-13: persist auto-routing decision slug.
                # DB column added by Plan 09 migration; write is harmless
                # until then because the column is nullable.
                auto_route_reason=auto_route_reason,
                objective_value=result.objective_value,
                credits_consumed=credits_needed,
                credits_base=credits_needed,
                origin="manual",
                is_async=False,
                created_at=now,
                started_at=now,
                completed_at=now,
            )
            self.db.add(row)
            self.db.commit()
        except Exception:
            logger.warning(
                "Failed to persist sync ModelExecution %s",
                execution_id,
                exc_info=True,
            )
            self.db.rollback()

    async def solve_multi_objective(
        self,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
        org: Organization,
        user: object | None,
        request: Request,
        total_credits: int,
        workspace_id: str | None = None,
    ) -> MultiObjectiveResult:
        """Full multi-objective solve with pre-pay + refund credit pattern."""
        execution_id = generate_id("exe_")
        timeout_seconds = PSS.get_int(self.db, "SOLVER_TIMEOUT_SECONDS")

        pareto_points: list[ParetoPoint] = await self._execute_with_credits(
            solve_fn=lambda: self.solver.solve_multi_objective(problem, config),
            credits_needed=total_credits,
            org=org,
            workspace_id=workspace_id,
            execution_id=execution_id,
            request=request,
            generator_label="multi_objective",
            timeout_seconds=timeout_seconds,
        )

        labels = [obj.label or f"Objective {i + 1}" for i, obj in enumerate(config.objectives)]

        return MultiObjectiveResult(
            pareto_points=pareto_points,
            total_credits_used=total_credits,
            mode=config.mode,
            n_solved=len(pareto_points),
            labels=labels,
        )

    async def solve_with_template(
        self,
        problem: OptimizationProblem,
        template_id: str,
        org: Organization,
        user: object | None,
        request: Request,
        credits_needed: int,
        workspace_id: str | None = None,
        solver_name: str | None = None,
    ) -> OptimizationResult:
        """Solve a template-rendered problem with pre-pay + refund."""
        execution_id = generate_id("exe_")
        timeout_seconds = PSS.get_int(self.db, "SOLVER_TIMEOUT_SECONDS")

        # Use the requested solver if specified, else the default — parity with
        # solve_single so template solves can target HiGHS/Hexaly/etc.
        effective_solver = (
            get_solver_service(solver_name=solver_name) if solver_name else self.solver
        )

        result: OptimizationResult = await self._execute_with_credits(
            solve_fn=lambda: effective_solver.solve(problem),
            credits_needed=credits_needed,
            org=org,
            workspace_id=workspace_id,
            execution_id=execution_id,
            request=request,
            generator_label=template_id,
            timeout_seconds=timeout_seconds,
        )

        updated_org = self.db.query(Organization).filter(Organization.id == org.id).first()
        result.credits_used = credits_needed
        result.credits_remaining = updated_org.credits_balance if updated_org else 0

        # Analytics
        self._log_analytics_template(user, org, request, template_id, credits_needed)

        return result

    async def _execute_with_credits(
        self,
        solve_fn: Callable[[], Any],
        credits_needed: int,
        org: Organization,
        workspace_id: str | None,
        execution_id: str,
        request: Request,
        generator_label: str,
        timeout_seconds: int,
    ) -> Any:
        """Pre-pay, execute solve_fn in thread pool, refund on any failure.

        Args:
            solve_fn: Zero-argument callable that calls the solver (run in thread pool).
            credits_needed: Credits to pre-pay and refund on failure.
            org: Authenticated organization.
            workspace_id: Optional workspace for pool-first deduction.
            execution_id: ID for credit transaction reference.
            request: FastAPI request (for error response verbose mode).
            generator_label: Label for SOLVE_TOTAL metric (e.g. "direct", "multi_objective",
                template_id).
            timeout_seconds: Timeout in seconds for asyncio.wait_for.

        Returns:
            Whatever solve_fn returns (OptimizationResult or list[ParetoPoint]).

        Raises:
            HTTPException 402: Insufficient credits (from _pre_pay_credits).
            HTTPException 429: Pool at capacity (from _check_pool_capacity) — raised BEFORE
                deduction.
            HTTPException 408: Solve timed out.
            Any exception from solve_fn is re-raised after refund.
        """
        # Check pool BEFORE paying — pool rejection must not consume credits.
        self._check_pool_capacity(request)

        # 2. Pre-pay credits AFTER pool check passes
        self._pre_pay_credits(org, credits_needed, workspace_id, execution_id)

        # 3. Execute with timeout
        loop = asyncio.get_running_loop()
        ACTIVE_SOLVES.inc()
        _solve_start = _time.monotonic()
        refunded = False
        try:
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(self.solver_pool, solve_fn),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError as e:
                SOLVE_TOTAL.labels(status="timeout", generator=generator_label).inc()
                self._refund_credits(org, credits_needed, workspace_id, execution_id)
                refunded = True
                raise HTTPException(
                    status_code=408,
                    detail=self._error_response(
                        "SOLVE_TIMEOUT",
                        f"Solve timed out after {timeout_seconds}s. "
                        "Use POST /api/v2/solve/async for complex problems.",
                        request,
                        timeout_seconds=timeout_seconds,
                    ),
                ) from e

            _solve_elapsed = _time.monotonic() - _solve_start
            SOLVE_DURATION.observe(_solve_elapsed)

            # Check for solver error before incrementing CREDITS_CONSUMED so
            # a refunded solve does not still count toward consumed credits.
            result_status = getattr(result, "status", None)
            if result_status == SolverStatus.ERROR:
                self._refund_credits(org, credits_needed, workspace_id, execution_id)
                refunded = True
                SOLVE_TOTAL.labels(status=result_status.value, generator=generator_label).inc()
            else:
                SOLVE_TOTAL.labels(
                    status=result_status.value if result_status else "optimal",
                    generator=generator_label,
                ).inc()
                CREDITS_CONSUMED.inc(credits_needed)

            return result

        except HTTPException:
            raise
        except Exception:
            if not refunded:
                self._refund_credits(org, credits_needed, workspace_id, execution_id)
            raise
        finally:
            ACTIVE_SOLVES.dec()

    def _pre_pay_credits(
        self,
        org: Organization,
        credits_needed: int,
        workspace_id: str | None,
        execution_id: str,
    ) -> None:
        """Deduct credits BEFORE solving (pre-pay pattern).

        Workspace pool is tried first when workspace_id is provided.
        Falls back to org balance via CreditsService.deduct_credits().
        """
        if workspace_id:
            try:
                workspace_credits_service.deduct_credits_for_solve(
                    db=self.db,
                    org=org,
                    workspace_id=workspace_id,
                    credits_needed=credits_needed,
                )
                self.db.commit()
                return
            except ValueError:
                # Pool exhausted -- fall through to org balance
                logger.debug(
                    "Workspace pool exhausted for %s, falling back to org balance",
                    workspace_id,
                )

        try:
            CreditsService.deduct_credits(
                db=self.db,
                organization_id=org.id,
                credits=credits_needed,
                description=f"Solve: {execution_id}",
                reference_type="solve",
                reference_id=execution_id,
            )
            self.db.commit()
        except InsufficientCreditsError as e:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "insufficient_credits",
                    "credits_needed": e.credits_needed,
                    "credits_available": e.credits_available,
                },
            ) from e

    def _refund_credits(
        self,
        org: Organization,
        credits_needed: int,
        workspace_id: str | None,
        execution_id: str,
    ) -> None:
        """Refund pre-paid credits on solve failure.

        Best-effort: logs errors but never raises.
        """
        try:
            credits_svc = CreditsService(self.db)
            credits_svc.refund_credits(
                organization_id=org.id,
                credits=credits_needed,
                description=f"{RefundReason.ORCHESTRATOR_FAILURE.value}: {execution_id}",
                reference_type="solve_refund",
                reference_id=execution_id,
            )
            self.db.commit()
        except Exception as refund_err:
            logger.error("Failed to refund credits: %s", refund_err)

    def _check_pool_capacity(self, request: Request) -> None:
        """Raise 429 if the solver thread pool is saturated."""
        pool_size = PSS.get_int(self.db, "SOLVER_POOL_SIZE")
        work_queue = getattr(self.solver_pool, "_work_queue", None)
        if work_queue is not None and work_queue.qsize() >= pool_size * 2:
            raise HTTPException(
                status_code=429,
                detail=self._error_response(
                    "POOL_EXHAUSTED",
                    "Server is at capacity. Please use the async solve endpoint: "
                    "POST /api/v2/solve/async",
                    request,
                    pool_size=pool_size,
                    suggested_endpoint="/api/v2/solve/async",
                ),
            )

    @staticmethod
    def _error_response(
        error_code: str, message: str, request: Request, **extra: object
    ) -> dict[str, object]:
        """Build error response dict, adding verbose details when debug header set."""
        response: dict[str, object] = {"error": error_code, "message": message}
        if request.headers.get("X-Jaot-Debug", "").lower() == "true":
            response["details"] = extra
        return response

    def _log_analytics_solve(
        self,
        user: object | None,
        org: Organization,
        request: Request,
        problem: OptimizationProblem,
        credits_needed: int,
        result: OptimizationResult,
    ) -> None:
        """Fire-and-forget analytics for solve endpoint."""
        try:
            from app.services.analytics_service import AnalyticsService
            from app.shared.constants import event_types as evt

            analytics = AnalyticsService(self.db)
            user_id = getattr(user, "id", "anonymous")
            analytics.log_event(
                user_id=user_id,
                org_id=org.id,
                event_type=evt.SOLVER_SOLVE,
                ip_address=request.client.host if request.client else None,
                metadata={
                    "credits_used": credits_needed,
                    "status": result.status.value,
                    "variables": len(problem.variables),
                },
            )
            # MCP origin detection
            if request.url.path.startswith("/mcp"):
                analytics.log_event(
                    user_id=user_id,
                    org_id=org.id,
                    event_type=evt.MCP_TOOL_CALL,
                    ip_address=request.client.host if request.client else None,
                    metadata={"tool_name": "solve_problem"},
                )
        except Exception:
            logger.debug("Failed to log analytics event", exc_info=True)

    def _log_analytics_template(
        self,
        user: object | None,
        org: Organization,
        request: Request,
        template_id: str,
        credits_needed: int,
    ) -> None:
        """Fire-and-forget analytics for template solve endpoint."""
        try:
            from app.services.analytics_service import AnalyticsService
            from app.shared.constants import event_types as evt

            analytics = AnalyticsService(self.db)
            user_id = getattr(user, "id", "anonymous")
            analytics.log_event(
                user_id=user_id,
                org_id=org.id,
                event_type=evt.TEMPLATE_USE,
                ip_address=request.client.host if request.client else None,
                metadata={
                    "template_id": template_id,
                    "credits_used": credits_needed,
                },
            )
        except Exception:
            logger.debug("Failed to log analytics event", exc_info=True)
