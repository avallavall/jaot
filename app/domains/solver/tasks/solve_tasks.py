"""Celery tasks for async optimization solving."""

import json
import logging
import os
import time
from typing import Any

from celery import current_task
from celery.exceptions import SoftTimeLimitExceeded

from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverQueueMismatchError,
)
from app.domains.solver.prepaid import get_prepaid_credits
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services import get_solver_service
from app.models import ExecutionStatus, ModelExecution, Organization, OrganizationModel
from app.schemas.optimization import OptimizationProblem
from app.services.credits_service import CreditsService
from app.shared.core.celery_app import celery_app
from app.shared.core.prometheus_metrics import (
    ACTIVE_SOLVES,
    CREDITS_CONSUMED,
    CREDITS_REFUNDED,
    SOLVE_DURATION,
    SOLVE_TOTAL,
    RefundReason,
)
from app.shared.db.session import SessionLocal
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

# Lazy-init singleton Redis connection for WebSocket pub/sub
_redis_client = None


def _get_redis_client() -> Any:
    """Get or create a singleton Redis client for WebSocket event publishing."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis

        redis_url = os.getenv("REDIS_URL", "")
        if not redis_url:
            return None
        # Bounded timeouts so a slow/unreachable Redis can never hang a worker on
        # a best-effort progress publish (the publish itself is fire-and-forget).
        _redis_client = redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
        _redis_client.ping()  # Verify connection
        return _redis_client
    except Exception as e:
        logger.debug(f"Redis not available for WebSocket pub/sub: {e}")
        return None


def _publish_ws_event(execution_id: str, data: dict[str, Any]) -> None:
    """Publish a WebSocket event to Redis pub/sub (best-effort).

    Publishes JSON-encoded data to channel ``ws:execution:{execution_id}``.
    Never raises — failures are logged at debug level and silently ignored.
    """
    try:
        client = _get_redis_client()
        if client is None:
            return
        channel = f"ws:execution:{execution_id}"
        client.publish(channel, json.dumps(data, default=str))
    except Exception as e:
        logger.debug(f"Failed to publish WebSocket event for {execution_id}: {e}")


def update_task_progress(
    progress: float,
    status: str,
    message: str,
    iteration: int | None = None,
    objective_value: float | None = None,
    gap: float | None = None,
) -> None:
    """Update task progress metadata for real-time monitoring."""
    if current_task:
        current_task.update_state(
            state="PROGRESS",
            meta={
                "progress": progress,
                "status": status,
                "message": message,
                "iteration": iteration,
                "objective_value": objective_value,
                "gap": gap,
                "timestamp": utcnow().isoformat(),
            },
        )


def _assert_queue_match(solver_name: str | None) -> None:
    """Reject a task whose requested solver does not match this worker's queue.

    No-op when ``SOLVER_QUEUE`` is unset (dev/test/monolithic worker).
    Error message contains only already-public solver and queue names.
    """
    expected_queue = os.getenv("SOLVER_QUEUE")
    if not expected_queue:
        return
    requested = solver_name or DEFAULT_SOLVER_NAME
    try:
        requested_queue = resolve_queue(solver_name)
    except SolverNotFoundError as exc:
        raise SolverQueueMismatchError(
            f"Worker on queue '{expected_queue}' received task for unknown solver '{requested}'."
        ) from exc
    if requested_queue != expected_queue:
        raise SolverQueueMismatchError(
            f"Worker on queue '{expected_queue}' cannot process solver "
            f"'{requested}' (expected queue '{requested_queue}')."
        )


def _was_cancelled_by_user(task_id: str, organization_id: str) -> bool:
    """Return True iff the ModelExecution for this task is in CANCELLED state.

    The cancel endpoint marks the ModelExecution status = CANCELLED BEFORE
    it revokes the Celery task, so the except-branch refund path must
    re-read the row (the in-memory ``problem_data`` reflects dispatch-time
    state). Opens its own SessionLocal so the caller does not leak
    connections on partial failure. Best-effort: on any DB error returns
    False (fail-open — the refund still fires; better to double-credit on
    a flaky DB than silently swallow the refund).
    """
    try:
        db = SessionLocal()
        try:
            cancelled_exec = (
                db.query(ModelExecution)
                .filter(
                    ModelExecution.celery_task_id == task_id,
                    ModelExecution.organization_id == organization_id,
                )
                .first()
            )
            return (
                cancelled_exec is not None
                and cancelled_exec.status == ExecutionStatus.CANCELLED.value
            )
        finally:
            db.close()
    except Exception as check_err:
        logger.warning(
            "Failed to check cancellation state for task %s: %s",
            task_id,
            check_err,
        )
        return False


def _refund_prepaid_credits(
    task_id: str,
    organization_id: str,
    prepaid_credits: int,
    reason: RefundReason,
    detail: str,
    *,
    check_cancellation: bool = False,
) -> bool:
    """Refund pre-paid credits for a failed async solve task, idempotently.

    Owns the SessionLocal + CreditsService + commit lifecycle so the two
    refund sites in ``solve_async`` (success-with-error branch and
    except-branch) collapse to a single call. Returns True iff a refund
    was actually issued (False when the task was cancelled by the user
    or when ``prepaid_credits <= 0``).

    Args:
        task_id: Celery task id — doubles as the ``reference_id`` for
            idempotency (a retry with the same task id returns the
            existing transaction instead of double-crediting).
        organization_id: Refund target.
        prepaid_credits: Amount to refund. A value <= 0 is a no-op.
        reason: Closed-enum :class:`RefundReason` that keys the metric
            label and the description prefix.
        detail: Free-form suffix for the description (typically the
            exception message or solver error_message, truncated to 200
            chars by the caller).
        check_cancellation: When True, call
            :func:`_was_cancelled_by_user` first and skip the refund if
            the ModelExecution is already in CANCELLED state. Used by
            the except-branch so SIGTERM from a user-cancel does not
            refund automatically.

    Returns:
        True if refund was issued, False if skipped (cancel / zero /
        DB / CreditsService error — all suppressed, task must still
        succeed).
    """
    if prepaid_credits <= 0:
        return False

    if check_cancellation and _was_cancelled_by_user(task_id, organization_id):
        logger.info(
            "Task %s was cancelled by user; skipping refund for %d credits.",
            task_id,
            prepaid_credits,
        )
        return False

    try:
        refund_db = SessionLocal()
        try:
            refund_service = CreditsService(refund_db)
            refund_service.refund_credits(
                organization_id=organization_id,
                credits=prepaid_credits,
                description=f"{reason.value} (task {task_id}): {str(detail)[:200]}",
                reference_type="solve_task",
                reference_id=task_id,
            )
            refund_db.commit()
            # E-19 — bump the bounded-label refund counter AFTER the DB
            # commit succeeds so a rolled-back refund does not inflate
            # the metric.
            CREDITS_REFUNDED.labels(reason=reason.value).inc(prepaid_credits)
            logger.info(
                "Refunded %d credits for task %s (reason=%s)",
                prepaid_credits,
                task_id,
                reason.value,
            )
            return True
        except Exception as refund_err:
            logger.error("Failed to refund credits for task %s: %s", task_id, refund_err)
            refund_db.rollback()
            return False
        finally:
            refund_db.close()
    except Exception as session_err:
        logger.error("Failed to create DB session for refund: %s", session_err)
        return False


def _mark_execution_failed(task_id: str, organization_id: str, error: str) -> None:
    """Mark the ModelExecution row for this task as failed (W1 sibling fix).

    ``solve_async`` historically never updated its ModelExecution row —
    status truth lived only in the Celery result backend, so every failure
    (including ``SoftTimeLimitExceeded`` from the worker-level soft time
    limit, W15/F-01) left a zombie 'pending' row in user-visible execution
    history. Best-effort: opens its own session, preserves terminal states
    (a user CANCELLED row is not a failure), and never raises — the task's
    own result/refund path must not be disturbed by a bookkeeping error.
    """
    try:
        db = SessionLocal()
        try:
            execution = (
                db.query(ModelExecution)
                .filter(
                    ModelExecution.celery_task_id == task_id,
                    ModelExecution.organization_id == organization_id,
                )
                .first()
            )
            if execution is None:
                return
            if execution.status in (
                ExecutionStatus.CANCELLED.value,
                ExecutionStatus.COMPLETED.value,
                ExecutionStatus.FAILED.value,
            ):
                return
            execution.status = ExecutionStatus.FAILED.value
            execution.error_message = str(error)[:2000]
            execution.completed_at = utcnow()
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to mark execution failed for task %s: %s", task_id, exc)


@celery_app.task(bind=True, name="solve_async")  # type: ignore[misc]
def solve_async(
    self: Any,
    problem_data: dict[str, Any],
    organization_id: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
    warm_start_execution_id: str | None = None,
    solver_name: str | None = None,
) -> dict[str, Any]:
    """
    Async task to solve an optimization problem.

    Args:
        problem_data: The optimization problem definition
        organization_id: Organization making the request
        user_id: Optional user ID for tracking
        workspace_id: Optional workspace ID for credit pool deduction
        warm_start_execution_id: Optional previous execution ID for warm start
        solver_name: Optional solver name override (Phase 5 / HIGH-04)

    Returns:
        Model result dictionary
    """
    task_id = self.request.id
    logger.info(f"Starting async solve task {task_id} for org {organization_id}")

    try:
        _assert_queue_match(solver_name)

        update_task_progress(0.0, "starting", "Initializing solver...")
        _publish_ws_event(
            task_id,
            {
                "type": "progress",
                "execution_id": task_id,
                "progress": 0.0,
                "status": "starting",
                "message": "Initializing solver...",
                "timestamp": utcnow().isoformat(),
            },
        )

        # Create solver instance (use requested solver if specified)
        solver = get_solver_service(solver_name=solver_name)

        update_task_progress(0.1, "parsing", "Parsing problem definition...")
        _publish_ws_event(
            task_id,
            {
                "type": "progress",
                "execution_id": task_id,
                "progress": 0.1,
                "status": "parsing",
                "message": "Parsing problem definition...",
                "timestamp": utcnow().isoformat(),
            },
        )

        problem = OptimizationProblem(**problem_data)

        warm_start_solution: dict[str, Any] | None = None
        if warm_start_execution_id:
            db = SessionLocal()
            try:
                warm_start_solution = _load_warm_start_from_db(
                    db, warm_start_execution_id, organization_id
                )
            finally:
                db.close()

        # Solve the problem
        start_time = time.time()
        update_task_progress(0.2, "solving", "Solving optimization problem...")
        _publish_ws_event(
            task_id,
            {
                "type": "progress",
                "execution_id": task_id,
                "progress": 0.2,
                "status": "solving",
                "message": "Solving optimization problem...",
                "timestamp": utcnow().isoformat(),
            },
        )

        ACTIVE_SOLVES.inc()
        try:
            # Phase 7.4 / D-01: platform-license model — HexalyAdapter loads
            # the license from /etc/jaot/hexaly.lic at __init__ time; no
            # per-org BYOL decrypt needed. All solvers go through the same
            # adapter path.
            result = solver.solve(problem, warm_start_solution=warm_start_solution)
        finally:
            ACTIVE_SOLVES.dec()
        execution_time = time.time() - start_time
        SOLVE_DURATION.observe(execution_time)

        # Record Prometheus metrics for the completed solve
        result_status = getattr(result, "status", None)
        status_label = result_status.value if result_status else "optimal"
        SOLVE_TOTAL.labels(status=status_label, generator="async").inc()
        prepaid_credits = get_prepaid_credits(problem_data)
        if prepaid_credits > 0 and status_label != "error":
            CREDITS_CONSUMED.inc(prepaid_credits)
        elif prepaid_credits > 0 and status_label == "error":
            # D-19: solver returned status=error (e.g. EXPR_PARSE_ERROR) without
            # raising — the task "succeeded" from Celery's view but delivered no
            # value. Refund here; the except-branch refund won't fire for
            # non-raising failures. Idempotent via
            # (org_id, REFUND, solve_task, task_id).
            err_detail = getattr(result, "error_message", None) or "solver_error"
            _refund_prepaid_credits(
                task_id=task_id,
                organization_id=organization_id,
                prepaid_credits=prepaid_credits,
                reason=RefundReason.SOLVER_LEVEL_ERROR,
                detail=err_detail,
            )
            # W1: keep the DB row truthful — without this the execution
            # stays 'pending' forever in user-visible history.
            _mark_execution_failed(task_id, organization_id, str(err_detail))

        # Extract solver metrics if available (MIP gap, bounds)
        metrics = None
        if hasattr(result, "gap") and result.gap is not None:
            metrics = {"gap": result.gap}
            if hasattr(result, "objective_value") and result.objective_value is not None:
                metrics["incumbent"] = result.objective_value

        update_task_progress(1.0, "completed", "Model found!")
        _publish_ws_event(
            task_id,
            {
                "type": "completed",
                "execution_id": task_id,
                "progress": 1.0,
                "status": "completed",
                "message": "Model found!",
                "timestamp": utcnow().isoformat(),
                "metrics": metrics,
            },
        )

        logger.info(f"Task {task_id} completed in {execution_time:.2f}s")

        # Phase 7.4 / D-13: extract auto-route telemetry threaded from the
        # enqueue site (solve.py async path) via problem_data side-channel.
        # The structured `auto_route_decision` log + SOLVER_AUTO_ROUTE_DECISIONS
        # counter are emitted EXACTLY ONCE at enqueue time in
        # app/api/v2/solve.py::solve_optimization_problem_async (lines 573-585).
        # Re-emitting here would double-count every async auto-routed solve
        # (WR-02). The auto-route decision itself is made at enqueue time
        # (select_solver runs in solve.py before this task ever runs), so the
        # enqueue-side emission is the canonical surface; the worker only
        # re-reports the threaded reason via the result payload.
        _async_auto_reason: str | None = problem_data.get("_auto_route_reason")
        _async_fallback: bool = bool(problem_data.get("_fallback_triggered", False))
        _async_solver_used: str = solver_name or DEFAULT_SOLVER_NAME

        result_payload: dict[str, Any] = {
            "status": "success",
            "task_id": task_id,
            "result": result.model_dump() if hasattr(result, "model_dump") else result,
            "execution_time_seconds": execution_time,
            # Phase 7.4 / D-13: hoist auto-route fields so GET async hoist works.
            "solver_used": _async_solver_used,
            "auto_route_reason": _async_auto_reason,
        }
        if _async_fallback:
            result_payload["warning"] = (
                "Hexaly temporarily unavailable; solved with SCIP (quadratic quality may differ)"
            )
        return result_payload

    except Exception as e:
        logger.error(f"Task {task_id} failed: {str(e)}")
        SOLVE_TOTAL.labels(status="error", generator="async").inc()

        # W15/F-01: SoftTimeLimitExceeded carries no useful message — give
        # the user-visible error_message and refund detail a clear reason.
        if isinstance(e, SoftTimeLimitExceeded):
            error_detail = (
                "Solve exceeded the worker time limit and was terminated. "
                "Pre-paid credits have been refunded."
            )
        else:
            error_detail = str(e)

        # Refund pre-paid credits on failure (D-19).
        # A user-triggered cancel (POST /solve/async/{id}/cancel) revokes the
        # task via SIGTERM which also flows into this except block. The cancel
        # endpoint marks the ModelExecution cancelled and sets
        # _prepaid_credits=0 BEFORE revoke, so ``check_cancellation=True``
        # suppresses the refund on user cancellation. ``problem_data`` is the
        # dispatch-time snapshot; the helper re-reads the ModelExecution row
        # to pick up late cancels.
        _refund_prepaid_credits(
            task_id=task_id,
            organization_id=organization_id,
            prepaid_credits=get_prepaid_credits(problem_data),
            reason=RefundReason.TASK_EXCEPTION,
            detail=error_detail,
            check_cancellation=True,
        )

        # W1: mark the row failed (no-op for CANCELLED — user cancel is
        # preserved). Covers SoftTimeLimitExceeded and every other raise.
        _mark_execution_failed(task_id, organization_id, error_detail)

        update_task_progress(1.0, "failed", str(e))
        _publish_ws_event(
            task_id,
            {
                "type": "failed",
                "execution_id": task_id,
                "progress": 1.0,
                "status": "failed",
                "message": str(e),
                "error": str(e),
                "timestamp": utcnow().isoformat(),
            },
        )
        return {
            "status": "error",
            "task_id": task_id,
            "error": str(e),
        }


def _load_warm_start_from_db(
    db: Any,
    execution_id: str,
    organization_id: str,
) -> dict[str, float] | None:
    """
    Load warm start solution from DB in Celery task context.

    Returns solution dict or None (non-fatal — logs warning on failure).
    """
    try:
        execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()

        if not execution:
            logger.warning(f"Warm start execution not found: {execution_id}")
            return None

        if execution.organization_id != organization_id:
            logger.warning(f"Warm start execution {execution_id} org mismatch")
            return None

        if execution.status != ExecutionStatus.COMPLETED.value:
            logger.warning(
                f"Warm start execution {execution_id} not completed (status={execution.status})"
            )
            return None

        if execution.solver_status not in ("optimal", "feasible"):
            logger.warning(
                f"Warm start execution {execution_id} solver_status={execution.solver_status}"
            )
            return None

        result_data = execution.result_data or {}
        solution = result_data.get("solution")
        if not solution or not isinstance(solution, dict):
            logger.warning(f"Warm start execution {execution_id} has no solution dict")
            return None

        logger.info(f"Loaded warm start from execution {execution_id}")
        return {k: float(v) for k, v in solution.items()}

    except Exception as e:
        logger.warning(f"Failed to load warm start from DB: {e}")
        return None


@celery_app.task(bind=True, name="solve_model_async")  # type: ignore[misc]
def solve_model_async(
    self: Any,
    execution_id: str,
    model_id: str,
    template: dict[str, Any],
    input_data: dict[str, Any],
    organization_id: str,
    base_credits: int = 1,
    solver_name: str | None = None,
    _prepaid_credits: int = 0,
) -> dict[str, Any]:
    """
    Async task to execute a model from the catalog.

    Args:
        execution_id: ID of the ModelExecution record
        model_id: ID of the OrganizationModel
        template: Template configuration for the solver
        input_data: Input parameters for the model
        organization_id: Organization making the request
        base_credits: Base credits to charge
        solver_name: Optional solver name (defaults to SCIP if None)

    Returns:
        Execution result dictionary
    """
    from app.domains.solver.services.template_engine import get_template_engine

    task_id = self.request.id
    logger.info(f"Starting model execution task {task_id} for execution {execution_id}")

    db = SessionLocal()
    execution = None
    try:
        _assert_queue_match(solver_name)

        execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()

        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

        execution.status = ExecutionStatus.RUNNING.value
        db.commit()

        update_task_progress(0.0, "starting", "Loading model configuration...")
        _publish_ws_event(
            execution_id,
            {
                "type": "progress",
                "execution_id": execution_id,
                "progress": 0.0,
                "status": "starting",
                "message": "Loading model configuration...",
                "timestamp": utcnow().isoformat(),
            },
        )

        model = db.query(OrganizationModel).filter(OrganizationModel.id == model_id).first()

        if not model:
            raise ValueError(f"Model {model_id} not found")

        update_task_progress(0.1, "building", "Building optimization problem...")
        _publish_ws_event(
            execution_id,
            {
                "type": "progress",
                "execution_id": execution_id,
                "progress": 0.1,
                "status": "building",
                "message": "Building optimization problem...",
                "timestamp": utcnow().isoformat(),
            },
        )

        # Transform input to optimization problem using template engine
        template_engine = get_template_engine()
        problem = template_engine.render(template, input_data)

        # Create solver (uses requested solver or default SCIP)
        solver = get_solver_service(solver_name=solver_name)

        # Solve
        start_time = time.time()
        update_task_progress(0.2, "solving", "Solving optimization problem...")
        _publish_ws_event(
            execution_id,
            {
                "type": "progress",
                "execution_id": execution_id,
                "progress": 0.2,
                "status": "solving",
                "message": "Solving optimization problem...",
                "timestamp": utcnow().isoformat(),
            },
        )

        ACTIVE_SOLVES.inc()
        try:
            result = solver.solve(problem)
        finally:
            ACTIVE_SOLVES.dec()
        execution_time_seconds = time.time() - start_time
        execution_time_ms = int(execution_time_seconds * 1000)
        SOLVE_DURATION.observe(execution_time_seconds)

        # Credits already calculated dynamically via calculate_credits() at pre-pay
        total_credits = base_credits

        # Extract solver metrics if available (MIP gap, bounds)
        metrics = None
        if hasattr(result, "gap") and result.gap is not None:
            metrics = {"gap": result.gap}
            if hasattr(result, "objective_value") and result.objective_value is not None:
                metrics["incumbent"] = result.objective_value

        # Store rendered problem so parse_problem() / file-export works
        execution.input_data = problem.model_dump(mode="json")
        execution.status = ExecutionStatus.COMPLETED.value
        execution.result_data = result.to_result_data()
        execution.execution_time_ms = execution_time_ms
        execution.solver_status = result.status.value
        execution.objective_value = result.objective_value
        execution.credits_consumed = total_credits
        execution.credits_compute = 0
        execution.completed_at = utcnow()

        # Deduct credits via CreditsService (row-locked, idempotent, with notification)
        CreditsService.deduct_credits(
            db=db,
            organization_id=organization_id,
            credits=total_credits,
            description=f"Async solve execution: {execution_id}",
            reference_type="execution",
            reference_id=execution_id,
        )
        SOLVE_TOTAL.labels(
            status=result.status.value,
            generator="model_async",
        ).inc()
        CREDITS_CONSUMED.inc(total_credits)

        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if org:
            org.credits_used_month += total_credits

        model.total_executions += 1
        model.total_credits_used += total_credits
        model.last_executed_at = utcnow()

        if model.catalog_model:
            model.catalog_model.total_executions += 1

        db.commit()

        try:
            from app.services.notification_service import NotificationService

            notification_service = NotificationService(db)
            notification_service.notify_execution_completed(
                user_id=execution.executed_by_user_id or "",
                organization_id=organization_id,
                execution_id=execution_id,
                model_name=model.display_name,
                objective_value=result.objective_value,
            )

            # Low-credits check is now handled automatically inside CreditsService
        except Exception as notify_error:
            logger.warning(f"Failed to send notification: {notify_error}")

        update_task_progress(1.0, "completed", "Model found!")
        _publish_ws_event(
            execution_id,
            {
                "type": "completed",
                "execution_id": execution_id,
                "progress": 1.0,
                "status": "completed",
                "message": "Model found!",
                "timestamp": utcnow().isoformat(),
                "metrics": metrics,
            },
        )

        logger.info(f"Execution {execution_id} completed in {execution_time_ms}ms")

        return {
            "status": "success",
            "execution_id": execution_id,
            "task_id": task_id,
            "result": {
                "model": result.solution,
                "objective_value": result.objective_value,
                "solver_status": result.status.value,
                "solve_time_seconds": result.solve_time_seconds,
            },
            "execution_time_ms": execution_time_ms,
            "credits_used": total_credits,
        }

    except Exception as e:
        logger.error(f"Execution {execution_id} failed: {str(e)}")
        SOLVE_TOTAL.labels(status="error", generator="model_async").inc()

        # Update execution record.
        # The cancel endpoint sets status="cancelled" BEFORE revoking the
        # Celery task, so SIGTERM may flow into this handler. When the
        # execution is already marked cancelled we preserve the cancellation
        # state and skip the base-credit deduction — a user cancellation is
        # not a solver failure.
        if execution:
            # Re-read to pick up status changes the cancel endpoint committed
            # on another session while this task was running.
            db.refresh(execution)

            if execution.status == ExecutionStatus.CANCELLED.value:
                logger.info(
                    "Execution %s was cancelled by user; skipping failure-path credit deduction.",
                    execution_id,
                )
                execution.error_message = execution.error_message or "Cancelled by user"
                execution.completed_at = execution.completed_at or utcnow()
                # credits_consumed stays at its pre-cancel value (typically None)
            else:
                execution.status = ExecutionStatus.FAILED.value
                execution.error_message = str(e)
                execution.completed_at = utcnow()

                # When the producer has pre-paid credits (the execute_model
                # async branch does this to match /solve/async), a solver
                # failure must refund — not re-deduct. Refund is idempotent
                # via record_transaction's (org, REFUND, execution,
                # execution_id) uniqueness scope.
                if _prepaid_credits > 0:
                    execution.credits_consumed = 0
                    try:
                        CreditsService(db).refund_credits(
                            organization_id=organization_id,
                            credits=_prepaid_credits,
                            description=(
                                f"{RefundReason.MODEL_EXECUTION_FAILED.value} "
                                f"(execution {execution_id}): {str(e)[:200]}"
                            ),
                            reference_type="execution",
                            reference_id=execution_id,
                        )
                    except Exception as credit_err:
                        logger.warning(
                            "Failed to refund pre-paid credits on failure: %s", credit_err
                        )
                else:
                    # Legacy path (no pre-pay): keep the historic
                    # deduct-on-failure behavior so callers that did NOT
                    # pre-pay (e.g. other dispatch sites) still record the
                    # charge. New producers should always pre-pay.
                    execution.credits_consumed = base_credits
                    try:
                        CreditsService.deduct_credits(
                            db=db,
                            organization_id=organization_id,
                            credits=base_credits,
                            description=f"Async solve execution (failed): {execution_id}",
                            reference_type="execution_failed",
                            reference_id=execution_id,
                        )
                        org = (
                            db.query(Organization)
                            .filter(Organization.id == organization_id)
                            .first()
                        )
                        if org:
                            org.credits_used_month += base_credits
                    except Exception as credit_err:
                        logger.warning("Failed to deduct base credits on failure: %s", credit_err)

            db.commit()

            try:
                from app.services.notification_service import NotificationService

                notification_service = NotificationService(db)
                notification_service.notify_execution_failed(
                    user_id=execution.executed_by_user_id or "",
                    organization_id=organization_id,
                    execution_id=execution_id,
                    model_name=model.display_name if model else "Unknown",
                    error=str(e),
                )
            except Exception as notify_error:
                logger.warning(f"Failed to send failure notification: {notify_error}")

        update_task_progress(1.0, "failed", str(e))
        _publish_ws_event(
            execution_id,
            {
                "type": "failed",
                "execution_id": execution_id,
                "progress": 1.0,
                "status": "failed",
                "message": str(e),
                "error": str(e),
                "timestamp": utcnow().isoformat(),
            },
        )

        return {
            "status": "error",
            "execution_id": execution_id,
            "task_id": task_id,
            "error": str(e),
        }

    finally:
        db.close()
