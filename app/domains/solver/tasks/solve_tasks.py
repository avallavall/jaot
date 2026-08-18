"""Celery tasks for async optimization solving."""

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from celery import current_task
from celery.exceptions import SoftTimeLimitExceeded

from app.domains.solver import execution_writer, ports
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverQueueMismatchError,
)
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services import get_solver_service
from app.domains.solver.services.auto_router import warning_for as auto_router_warning
from app.domains.solver.warm_start import load_warm_start_solution
from app.models import ModelExecution
from app.models.model_project import ModelProject
from app.schemas.optimization import (
    MultiObjectiveConfig,
    MultiObjectiveResult,
    OptimizationProblem,
    SolverStatus,
)
from app.schemas.solution_structure import annotate_variable_structure
from app.shared.core.celery_app import celery_app
from app.shared.core.prometheus_metrics import (
    ACTIVE_SOLVES,
    SOLVE_DURATION,
    SOLVE_TOTAL,
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


def _make_solve_progress_publisher(execution_id: str) -> Callable[[Any], None]:
    """Build the Live Solve ``on_progress`` callback for an async solve.

    The returned callable streams each new incumbent (a ``ProgressPoint``) to the
    existing ``ws:execution:{execution_id}`` channel. Best-effort: ``_publish_ws_event``
    has bounded socket timeouts and never raises, and the SCIP event handler swallows
    callback errors — so a solve can never be blocked or aborted by progress streaming.
    Solvers whose ``capabilities.supports_progress`` is False never invoke it.
    """

    def _publish(point: Any) -> None:
        _publish_ws_event(
            execution_id,
            {"type": "solve_progress", "execution_id": execution_id, **point.model_dump()},
        )

    return _publish


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


def _listing_id_for(model: ModelProject) -> str:
    """The listing a run should be attributed to.

    A fork credits the listing it came from; a project with its own listing
    credits that. Returns the project id either way, which is also the listing PK.
    """
    if model.source_type == "marketplace" and model.source_ref:
        return model.source_ref
    return model.id


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
        workspace_id: Optional workspace ID (provenance)
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
                warm_start_solution = load_warm_start_solution(
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
            #
            # Live Solve: stream each new incumbent to ws:execution:{task_id}
            # (task_id == execution_id). Only solvers with supports_progress fire it.
            result = solver.solve(
                problem,
                warm_start_solution=warm_start_solution,
                on_progress=_make_solve_progress_publisher(task_id),
            )
        finally:
            ACTIVE_SOLVES.dec()
        execution_time = time.time() - start_time
        SOLVE_DURATION.observe(execution_time)

        # Record Prometheus metrics for the completed solve
        result_status = getattr(result, "status", None)
        status_label = result_status.value if result_status else "optimal"
        SOLVE_TOTAL.labels(status=status_label, generator="async").inc()
        if status_label == "error":
            # Solver returned status=error (e.g. EXPR_PARSE_ERROR) without
            # raising — the task "succeeded" from Celery's view but delivered
            # no value. W1: keep the DB row truthful — without this the
            # execution stays 'pending' forever in user-visible history.
            err_detail = getattr(result, "error_message", None) or "solver_error"
            execution_writer.mark_failed_by_task(task_id, organization_id, str(err_detail))

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
        # ``_fallback_triggered`` is threaded through too but no longer read
        # here: the warning comes from the reason slug, which says the same
        # thing and says it for every routing outcome rather than one.
        _async_auto_reason: str | None = problem_data.get("_auto_route_reason")
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
        # Written once in the router, next to the slug it belongs to, so a new
        # routing outcome cannot inherit a sentence about a different one.
        _async_warning = auto_router_warning(_async_auto_reason, _async_solver_used)
        if _async_warning is not None:
            result_payload["warning"] = _async_warning

        # W1 sibling: persist the successful solve onto its ModelExecution row so the
        # history table + detail page are truthful immediately, instead of staying a
        # 'pending' zombie until the ~30-min reaper (which never persists result_data).
        # A status_label=='error' row was already marked failed above; skip it here.
        if status_label != "error":
            execution_writer.mark_completed_by_task(
                task_id=task_id,
                organization_id=organization_id,
                result=result,
                execution_time_seconds=execution_time,
                solver_name=_async_solver_used,
            )

        return result_payload

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e!s}")
        SOLVE_TOTAL.labels(status="error", generator="async").inc()

        # W15/F-01: SoftTimeLimitExceeded carries no useful message — give
        # the user-visible error_message a clear reason.
        if isinstance(e, SoftTimeLimitExceeded):
            error_detail = "Solve exceeded the worker time limit and was terminated."
        else:
            error_detail = str(e)

        # W1: mark the row failed (no-op for CANCELLED — user cancel is
        # preserved). Covers SoftTimeLimitExceeded and every other raise.
        execution_writer.mark_failed_by_task(task_id, organization_id, error_detail)

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


@celery_app.task(bind=True, name="solve_multi_objective_async")  # type: ignore[misc]
def solve_multi_objective_async(
    self: Any,
    problem_data: dict[str, Any],
    config_data: dict[str, Any],
    organization_id: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Async multi-objective solve (ADR-007 S4b).

    Runs the self-contained scalarization loop (``SolverService.solve_multi_objective``,
    always SCIP) and persists the Pareto front under the nested ``multi_objective``
    result_data — an empty front (infeasible) is a completed run, matching the sync
    contract. Mirrors ``solve_async``'s writer discipline.
    """
    task_id = self.request.id
    logger.info(f"Starting async multi-objective solve {task_id} for org {organization_id}")

    try:
        _assert_queue_match("scip")  # scalarization always runs on the SCIP queue

        _publish_ws_event(
            task_id,
            {
                "type": "progress",
                "execution_id": task_id,
                "progress": 0.0,
                "status": "starting",
                "message": "Initializing multi-objective solve...",
                "timestamp": utcnow().isoformat(),
            },
        )

        problem = OptimizationProblem(**problem_data)
        config = MultiObjectiveConfig(**config_data)
        solver = get_solver_service()

        start_time = time.time()
        ACTIVE_SOLVES.inc()
        try:
            pareto_points = solver.solve_multi_objective(problem, config)
        finally:
            ACTIVE_SOLVES.dec()
        execution_time = time.time() - start_time
        SOLVE_DURATION.observe(execution_time)

        labels = [obj.label or f"Objective {i + 1}" for i, obj in enumerate(config.objectives)]
        mo_result = MultiObjectiveResult(
            pareto_points=pareto_points,
            mode=config.mode,
            n_solved=len(pareto_points),
            labels=labels,
        )
        # Nested result_data: single-solve keys stay null (a Pareto front, not one answer).
        result_data = {
            "multi_objective": mo_result.model_dump(mode="json"),
            "objective_value": None,
            "solver_status": "optimal",
        }

        SOLVE_TOTAL.labels(status="optimal", generator="multi_objective").inc()

        # Persist the terminal row (parity with solve_async's W1 sibling) so the run
        # shows up in history immediately instead of staying a 'pending' zombie.
        execution_writer.mark_multi_objective_completed_by_task(
            task_id=task_id,
            organization_id=organization_id,
            result_data=result_data,
            execution_time_seconds=execution_time,
        )

        _publish_ws_event(
            task_id,
            {
                "type": "completed",
                "execution_id": task_id,
                "progress": 1.0,
                "status": "completed",
                "message": "Pareto front computed",
                "timestamp": utcnow().isoformat(),
                "metrics": {"n_solved": mo_result.n_solved},
            },
        )
        logger.info(f"Multi-objective task {task_id} completed in {execution_time:.2f}s")

        return {
            "status": "success",
            "task_id": task_id,
            "multi_objective": True,
            "result": mo_result.model_dump(mode="json"),
            "execution_time_seconds": execution_time,
        }

    except Exception as e:
        logger.error(f"Multi-objective task {task_id} failed: {e!s}")
        SOLVE_TOTAL.labels(status="error", generator="multi_objective").inc()

        # SoftTimeLimitExceeded carries no useful message; give a clear reason.
        if isinstance(e, SoftTimeLimitExceeded):
            error_detail = (
                "Multi-objective solve exceeded the worker time limit and was terminated."
            )
        else:
            error_detail = str(e)

        execution_writer.mark_failed_by_task(task_id, organization_id, error_detail)

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
            "error": error_detail,
        }


@celery_app.task(bind=True, name="solve_model_async")  # type: ignore[misc]
def solve_model_async(
    self: Any,
    execution_id: str,
    model_id: str,
    template: dict[str, Any] | None,
    input_data: dict[str, Any],
    organization_id: str,
    solver_name: str | None = None,
    problem_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Async task to execute one of the organization's models (ModelProject).

    Args:
        execution_id: ID of the ModelExecution record
        model_id: ID of the ModelProject being executed
        template: Generator template to render with ``input_data`` (generator-backed
            models); None for a static model
        input_data: Input parameters for the generator (ignored for static models)
        organization_id: Organization making the request
        solver_name: Optional solver name (defaults to SCIP if None)
        problem_data: The validated OptimizationProblem payload of a static model
            (used when ``template`` is None)

    Returns:
        Execution result dictionary
    """
    from app.domains.solver.services.template_engine import get_template_engine

    task_id = self.request.id
    logger.info("Starting model execution task %s for execution %s", task_id, execution_id)

    db = SessionLocal()
    execution = None
    model: ModelProject | None = None
    try:
        _assert_queue_match(solver_name)

        execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()

        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

        execution_writer.apply_running(execution)
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

        model = db.query(ModelProject).filter(ModelProject.id == model_id).first()

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

        # Generator-backed models render input through the template engine;
        # static models ship their validated problem payload directly.
        if template is not None:
            template_engine = get_template_engine()
            problem = template_engine.render(template, input_data)
        elif problem_data is not None:
            problem = OptimizationProblem.model_validate(problem_data)
        else:
            raise ValueError(f"Model {model_id} has neither a template nor problem_data")

        # Recover flat variable index structure (family/index_tuple, A1) so the
        # adapters copy it onto the solution. /solve and /solve/async annotate at
        # enqueue, but THIS task is fed by /models/{id}/execute (template render or
        # stored problem_data), which doesn't — without this, marketplace/template
        # executions silently lose the grouped solution view. No-op for
        # JModel-compiled problems (already annotated authoritatively).
        annotate_variable_structure(problem)

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

        # ADR-007 S6: a solver-internal error comes back as status=ERROR WITHOUT
        # raising (SolverService.solve swallows exceptions into an ERROR result).
        # Mirror the historic sync contract: mark the row failed — a solve that
        # delivered no result must never look completed.
        if result.status == SolverStatus.ERROR:
            error_message = result.error_message or "Solver returned an error"
            execution.input_data = problem.model_dump(mode="json")
            if execution_writer.apply_failed(execution, error=error_message):
                execution.result_data = result.to_result_data()
                execution.execution_time_ms = execution_time_ms
                execution.solver_status = result.status.value
            # A failed run counts too — otherwise the listing's success rate has
            # no denominator and every model looks flawless.
            ports.solve_events().listing_executed(
                db, _listing_id_for(model), succeeded=False, execution_time_ms=None
            )
            db.commit()
            SOLVE_TOTAL.labels(status="error", generator="model_async").inc()
            update_task_progress(1.0, "failed", error_message)
            _publish_ws_event(
                execution_id,
                {
                    "type": "failed",
                    "execution_id": execution_id,
                    "progress": 1.0,
                    "status": "failed",
                    "message": error_message,
                    "error": error_message,
                    "timestamp": utcnow().isoformat(),
                },
            )
            return {
                "status": "error",
                "execution_id": execution_id,
                "task_id": task_id,
                "error": error_message,
                "result_data": result.to_result_data(),
                "execution_time_ms": execution_time_ms,
                "solver_status": result.status.value,
            }

        # Extract solver metrics if available (MIP gap, bounds)
        metrics = None
        if hasattr(result, "gap") and result.gap is not None:
            metrics = {"gap": result.gap}
            if hasattr(result, "objective_value") and result.objective_value is not None:
                metrics["incumbent"] = result.objective_value

        # Store rendered problem so parse_problem() / file-export works, then let
        # the single writer own the terminal-success columns (ADR-007 S3).
        execution.input_data = problem.model_dump(mode="json")
        execution_writer.apply_completed(
            execution,
            result=result,
            execution_time_seconds=execution_time_seconds,
        )
        SOLVE_TOTAL.labels(
            status=result.status.value,
            generator="model_async",
        ).inc()

        # Roll the execution onto the marketplace listing (a fork bumps its SOURCE
        # listing; a project with its own listing bumps that). Per-project counts
        # are computed from model_executions — no per-project counter.
        events = ports.solve_events()
        events.listing_executed(
            db, _listing_id_for(model), succeeded=True, execution_time_ms=execution_time_ms
        )

        db.commit()

        try:
            events.solve_completed(
                db,
                user_id=execution.executed_by_user_id or "",
                organization_id=organization_id,
                execution_id=execution_id,
                model_name=model.name,
                objective_value=result.objective_value,
            )
            # The notification writer only flushes; without this commit the row
            # dies with the session when the task ends — the log line printed,
            # the bell stayed empty, and no test saw it because in tests the
            # session outlives the task. Committed apart from the solve's own
            # commit above so a notification failure can never take the
            # execution's persistence with it.
            db.commit()
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
        }

    except Exception as e:
        logger.error(f"Execution {execution_id} failed: {e!s}")
        SOLVE_TOTAL.labels(status="error", generator="model_async").inc()

        # Update execution record.
        # The cancel endpoint sets status="cancelled" BEFORE revoking the
        # Celery task, so SIGTERM may flow into this handler. When the
        # execution is already marked cancelled we preserve the cancellation
        # state — a user cancellation is not a solver failure.
        if execution:
            # Re-read to pick up status changes the cancel endpoint committed
            # on another session while this task was running.
            db.refresh(execution)

            # The single writer's terminal-wins guard: apply_failed is a no-op
            # (returns False) when the row is already CANCELLED.
            if not execution_writer.apply_failed(execution, error=str(e)):
                logger.info(
                    "Execution %s already terminal (user cancel); preserving it.",
                    execution_id,
                )
                execution.error_message = execution.error_message or "Cancelled by user"
                execution.completed_at = execution.completed_at or utcnow()
            elif model is not None:
                # Only a genuine failure counts against the listing: a user
                # cancellation says nothing about whether the model works, and a
                # crash before the model loaded has no listing to attribute.
                ports.solve_events().listing_executed(
                    db, _listing_id_for(model), succeeded=False, execution_time_ms=None
                )

            db.commit()

            try:
                ports.solve_events().solve_failed(
                    db,
                    user_id=execution.executed_by_user_id or "",
                    organization_id=organization_id,
                    execution_id=execution_id,
                    # model.name, as in the success path: display_name lives on
                    # the LISTING — reading it here raised AttributeError into
                    # the swallow below, so this notification never went out.
                    model_name=model.name if model else "Unknown",
                    error=str(e),
                )
                # Same as the success path: the writer only flushes, and the
                # failed row was already committed above — this commit persists
                # only the notification.
                db.commit()
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
