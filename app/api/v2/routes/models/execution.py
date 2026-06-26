"""Model execution endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.api.v2.deps.solve_maintenance_gate import solve_maintenance_gate
from app.api.v2.solve import calculate_credits
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.prepaid import clear_prepaid_credits
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services.solver_service import SolverService, get_solver_service
from app.domains.solver.services.template_engine import TemplateEngine, get_template_engine
from app.domains.solver.time_limits import compute_celery_time_limits
from app.models import ExecutionStatus, ModelExecution, Organization, OrganizationModel, User
from app.schemas.model import (
    ExecuteModelRequest,
    ExecutionListResponse,
    ModelExecutionResponse,
)
from app.schemas.optimization import OptimizationProblem
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.shared.core.prometheus_metrics import RefundReason
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["execution"])


class PreviewRequest(BaseModel):
    input_data: dict[str, Any]


@router.post("/{model_id}/preview", response_model=OptimizationProblem)
async def preview_model(
    model_id: str,
    body: PreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    template_engine: TemplateEngine = Depends(get_template_engine),
) -> OptimizationProblem:
    """Render a model template and return the OptimizationProblem without solving."""
    model = (
        db.query(OrganizationModel)
        .filter(
            OrganizationModel.id == model_id,
            OrganizationModel.organization_id == current_user.organization_id,
            OrganizationModel.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not model:
        raise HTTPException(status_code=404, detail="Model not found or inactive")

    if model.catalog_model:
        template = {
            "generator": model.catalog_model.generator_type,
            "input_fields": model.catalog_model.input_fields,
        }
    elif model.private_definition:
        template = {
            "generator": model.private_definition.get("generator_type", "generic"),
            "input_fields": (model.private_definition or {}).get("input_fields", []),
        }
    else:
        raise HTTPException(status_code=500, detail="Model has no definition")

    return template_engine.render(template, body.input_data)


@router.post(
    "/{model_id}/execute",
    operation_id="execute_model",
    dependencies=[Depends(solve_maintenance_gate)],
)
async def execute_model(
    model_id: str,
    body: ExecuteModelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    template_engine: TemplateEngine = Depends(get_template_engine),
    solver_name: str | None = Query(default=None, max_length=32),
) -> ModelExecutionResponse | dict[str, Any]:
    """Execute an activated model with the provided input data.

    Optional ``solver_name`` selects the solver (``scip``, ``highs``,
    ``hexaly``) or ``auto`` routing; omit for the default.
    """
    model = (
        db.query(OrganizationModel)
        .filter(
            OrganizationModel.id == model_id,
            OrganizationModel.organization_id == current_user.organization_id,
            OrganizationModel.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not model:
        raise HTTPException(status_code=404, detail="Model not found or inactive")

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Determine generator type
    if model.catalog_model:
        generator_type = model.catalog_model.generator_type
    elif model.private_definition:
        generator_type = model.private_definition.get("generator_type", "generic")
    else:
        raise HTTPException(status_code=500, detail="Model has no definition")

    if model.catalog_model:
        template = {
            "generator": generator_type,
            "input_fields": model.catalog_model.input_fields,
        }
    else:
        template = {
            "generator": generator_type,
            "input_fields": (model.private_definition or {}).get("input_fields", []),
        }

    # Override default solver if solver_name specified (Phase 5 / HIGH-04)
    if solver_name is not None:
        try:
            solver = get_solver_service(solver_name=solver_name)
        except (SolverNotFoundError, SolverUnavailableError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    problem = template_engine.render(template, body.input_data)
    # Phase 7.4 / D-02 / PRC-01: pre-pay the multiplier-adjusted credit cost.
    # When solver_name is None at this tier, fall back to DEFAULT_SOLVER_NAME
    # (matches line 163 `solver_name or DEFAULT_SOLVER_NAME` for the
    # ModelExecution row's solver_name column).
    effective_solver_for_pricing = solver_name or DEFAULT_SOLVER_NAME
    base_credits = calculate_credits(problem, solver_name=effective_solver_for_pricing, db=db)

    if org.credits_balance < base_credits:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits. Need {base_credits}, have {org.credits_balance}",
        )

    problem_data = problem.model_dump(mode="json")

    execution = ModelExecution(
        id=generate_id("exe_"),
        organization_model_id=model_id,
        organization_id=current_user.organization_id,
        executed_by_user_id=current_user.id,
        input_data=problem_data,
        status=ExecutionStatus.PENDING.value if body.async_mode else ExecutionStatus.RUNNING.value,
        credits_base=base_credits,
        started_at=utcnow(),
        solver_name=solver_name or DEFAULT_SOLVER_NAME,
    )
    db.add(execution)
    db.commit()

    # Handle async mode
    if body.async_mode:
        from app.domains.solver.tasks.solve_tasks import solve_model_async

        # get_solver_service above has already validated solver_name;
        # resolve_queue is a defense-in-depth check against future drift.
        try:
            target_queue = resolve_queue(solver_name)
        except SolverNotFoundError as exc:
            execution.status = ExecutionStatus.FAILED.value
            execution.error_message = str(exc)
            execution.completed_at = utcnow()
            db.commit()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # WR-07 (Phase 6): pre-pay credits BEFORE apply_async so this
        # endpoint matches the /api/v2/solve/async contract (D-19). The
        # Celery task refunds on solver failure; a broker failure here
        # surfaces HTTP 500 and leaves a refunded, cancelled execution.
        try:
            CreditsService.deduct_credits(
                db=db,
                organization_id=current_user.organization_id,
                credits=base_credits,
                description=f"Async model execution pre-pay: {execution.id}",
                reference_type="execution",
                reference_id=execution.id,
            )
            db.commit()
        except InsufficientCreditsError as e:
            execution.status = ExecutionStatus.FAILED.value
            execution.error_message = "Insufficient credits"
            execution.completed_at = utcnow()
            db.commit()
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "insufficient_credits",
                    "credits_needed": e.credits_needed,
                    "credits_available": e.credits_available,
                },
            ) from e

        # W15/F-01: derive Celery soft/hard kill limits from the rendered
        # problem's own solver time limit so a hung worker child cannot pin
        # the queue forever (the soft-limit except-branch refunds + marks
        # the execution failed; the hard limit SIGKILLs and the reaper
        # reconciles).
        soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)

        try:
            task = solve_model_async.apply_async(
                kwargs={
                    "execution_id": execution.id,
                    "model_id": model_id,
                    "template": template,
                    "input_data": body.input_data,
                    "organization_id": current_user.organization_id,
                    "base_credits": base_credits,
                    "solver_name": solver_name,
                    "_prepaid_credits": base_credits,
                },
                queue=target_queue,
                soft_time_limit=soft_limit,
                time_limit=hard_limit,
            )
        except Exception as exc:
            # Broker down or routing error after pre-pay — refund idempotently
            # to avoid orphan deductions. The ModelExecution is marked failed
            # so the dashboard reflects the outcome.
            logger.error(
                "apply_async failed for execution %s; refunding %d credits: %s",
                execution.id,
                base_credits,
                exc,
            )
            try:
                CreditsService(db).refund_credits(
                    organization_id=current_user.organization_id,
                    credits=base_credits,
                    description=f"{RefundReason.ENQUEUE_FAILED.value}: {execution.id}",
                    reference_type="execution",
                    reference_id=execution.id,
                )
                db.commit()
            except Exception:
                logger.warning(
                    "Failed to refund credits after apply_async failure for %s",
                    execution.id,
                    exc_info=True,
                )
                db.rollback()
            execution.status = ExecutionStatus.FAILED.value
            execution.error_message = f"Failed to enqueue task: {exc}"
            execution.completed_at = utcnow()
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

        return {
            "id": execution.id,
            "execution_id": execution.id,
            "organization_model_id": model_id,
            "status": "pending",
            "task_id": task.id,
            "ws_url": f"/api/v2/ws/executions/{execution.id}",
            "poll_url": f"/api/v2/models/async/{task.id}",
            "message": "Task queued for processing",
        }

    try:
        # Synchronous execution (problem already generated above for credit calc)
        start_time = utcnow()
        result = solver.solve(problem)
        end_time = utcnow()

        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
        total_credits = base_credits

        execution.status = ExecutionStatus.COMPLETED.value
        execution.result_data = result.to_result_data()
        execution.execution_time_ms = execution_time_ms
        execution.solver_status = result.status.value
        execution.objective_value = result.objective_value
        execution.credits_consumed = total_credits
        execution.credits_compute = 0
        execution.completed_at = end_time

        CreditsService.deduct_credits(
            db=db,
            organization_id=org.id,
            credits=total_credits,
            description=f"Model execution: {execution.id}",
            reference_type="execution",
            reference_id=execution.id,
        )
        org.credits_used_month += total_credits

        model.total_executions += 1
        model.total_credits_used += total_credits
        model.last_executed_at = end_time

        if model.catalog_model:
            model.catalog_model.total_executions += 1

        db.commit()
        db.refresh(execution)

        return ModelExecutionResponse.model_validate(execution)

    except Exception as e:
        execution.status = ExecutionStatus.FAILED.value
        execution.error_message = str(e)
        execution.completed_at = utcnow()
        execution.credits_consumed = base_credits

        try:
            CreditsService.deduct_credits(
                db=db,
                organization_id=org.id,
                credits=base_credits,
                description=f"Model execution (failed): {execution.id}",
                reference_type="execution_failed",
                reference_id=execution.id,
            )
            org.credits_used_month += base_credits
        except Exception as credit_err:
            logger.warning("Failed to deduct credits on execution failure: %s", credit_err)

        db.commit()
        db.refresh(execution)

        return ModelExecutionResponse.model_validate(execution)


@router.get("/async/{task_id}")
async def get_async_execution_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
        return {
            "task_id": task_id,
            "execution_id": execution.id,
            "status": "running",
            **result.info,
        }
    if result.state == "SUCCESS":
        celery_result = result.result

        if isinstance(celery_result, dict):
            inner_result = celery_result.get("result", celery_result)
            exec_time = celery_result.get("execution_time_ms")
            credits = celery_result.get("credits_used")
            exec_id = celery_result.get("execution_id") or execution.id
        else:
            inner_result = celery_result
            exec_time = None
            credits = None
            exec_id = execution.id

        if credits is None or exec_time is None:
            db.refresh(execution)
            if credits is None:
                credits = execution.credits_consumed
            if exec_time is None:
                exec_time = execution.execution_time_ms

        return {
            "task_id": task_id,
            "execution_id": exec_id,
            "status": "completed",
            "result": inner_result,
            "execution_time_ms": exec_time,
            "credits_used": credits,
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


@router.post("/async/{task_id}/cancel")
async def cancel_model_execution(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
        raise HTTPException(status_code=404, detail="Execution not found or not authorized")

    result = AsyncResult(task_id, app=celery_app)

    if result.state in ["SUCCESS", "FAILURE"]:
        return {
            "task_id": task_id,
            "execution_id": execution.id,
            "cancelled": False,
            "message": f"Task already {result.state.lower()}, cannot cancel",
        }

    # Mark the execution cancelled BEFORE revoking the Celery task so
    # solve_model_async's except handler can detect the user-triggered
    # cancellation and suppress the failure-path credit deduction. Using
    # an immutable copy on input_data satisfies the project immutability
    # rule.
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

    return {
        "task_id": task_id,
        "execution_id": execution.id,
        "cancelled": True,
        "message": "Execution cancelled",
    }


@router.get("/{model_id}/executions", response_model=ExecutionListResponse)
async def list_model_executions(
    model_id: str,
    status: str | None = Query(None),
    origin: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExecutionListResponse:
    """List execution history for a specific model."""
    model = (
        db.query(OrganizationModel)
        .filter(
            OrganizationModel.id == model_id,
            OrganizationModel.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    query = db.query(ModelExecution).filter(
        ModelExecution.organization_model_id == model_id,
    )

    if status:
        query = query.filter(ModelExecution.status == status)

    if origin:
        query = query.filter(ModelExecution.origin == origin)

    query = query.order_by(ModelExecution.created_at.desc())

    executions, total = paginate_query(query, page, page_size)

    return ExecutionListResponse(
        items=[ModelExecutionResponse.model_validate(e) for e in executions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/executions/all", response_model=ExecutionListResponse)
async def list_all_executions(
    status: str | None = Query(None),
    origin: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExecutionListResponse:
    """List all executions for the organization."""
    query = db.query(ModelExecution).filter(
        ModelExecution.organization_id == current_user.organization_id,
    )

    if status:
        query = query.filter(ModelExecution.status == status)

    if origin:
        query = query.filter(ModelExecution.origin == origin)

    query = query.order_by(ModelExecution.created_at.desc())

    executions, total = paginate_query(query, page, page_size)

    return ExecutionListResponse(
        items=[ModelExecutionResponse.model_validate(e) for e in executions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/executions/{execution_id}",
    response_model=ModelExecutionResponse,
    operation_id="get_execution",
)
async def get_execution(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModelExecutionResponse:
    """Get details of a specific execution."""
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    return ModelExecutionResponse.model_validate(execution)
