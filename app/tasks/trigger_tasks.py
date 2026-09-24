"""Celery task for async trigger-based solve runs.

Triggered by TriggerService.fire_trigger() after a /fire request is validated.
Loads the pinned model version, applies overrides, runs the solver, and
delivers an outbound webhook on completion. Also creates a ModelExecution row
so triggered solves appear alongside manual solves in the execution history.
"""

import logging
import secrets
import time
from typing import Any

from app.shared.core.celery_app import celery_app
from app.shared.db import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="app.tasks.trigger_tasks.trigger_solve_task",
    max_retries=0,
)
def trigger_solve_task(
    self: Any,
    run_id: str,
    trigger_id: str,
    override_data: dict[str, Any] | None,
    solver_name: str | None = None,
    time_limit_seconds: float | None = None,
) -> dict[str, Any]:
    """Execute a triggered solve run asynchronously.

    Steps:
    1. Load TriggerRun and SolveTrigger from DB
    2. Mark run as "running"
    3. Load pinned ModelVersion canvas/model JSON
    4. Apply overrides via TriggerService.apply_overrides()
    5. Parse merged model into OptimizationProblem
    6. Solve via SolverService
    7. Create ModelExecution row with origin='triggered'
    8. Update TriggerRun record (status, result, timing)
    9. Send in-app notification to trigger creator
    10. Deliver outbound webhook
    11. Close DB session

    Args:
        run_id: TriggerRun PK to update.
        trigger_id: SolveTrigger PK.
        override_data: Override key-value pairs supplied by the caller.
        solver_name: The effective solver, resolved when the run was queued so
            the task landed on that solver's worker. ``None`` (a message queued
            before this argument existed) resolves it here.
        time_limit_seconds: The limit the Celery time limits were derived from.

    Returns:
        Dict with run status and summary.
    """
    db = SessionLocal()
    start_time = time.monotonic()
    from app.shared.utils.datetime_helpers import utcnow as _utcnow  # noqa: PLC0415

    start_datetime = _utcnow()

    try:
        from app.models.trigger import SolveTrigger, TriggerRun  # noqa: PLC0415

        run = db.query(TriggerRun).filter(TriggerRun.id == run_id).first()
        if not run:
            logger.error("TriggerRun %s not found", run_id)
            return {"status": "error", "error": "run_not_found"}

        trigger = db.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
        if not trigger:
            logger.error("SolveTrigger %s not found for run %s", trigger_id, run_id)
            run.status = "failed"
            run.error_message = "Trigger configuration not found"
            db.commit()
            return {"status": "failed"}

        # A run the reaper settled while this task waited in the queue must not
        # be brought back. Writing 'running' over 'failed' resurrects a row the
        # cron overlap gate has already been told is finished, so the trigger
        # would now have two live runs of itself.
        if run.status in ("completed", "failed", "cancelled", "skipped_overlap"):
            logger.warning(
                "TriggerRun %s was already settled as '%s' before this task started; "
                "not running it again",
                run_id,
                run.status,
            )
            return {"status": run.status, "reason": "already_settled"}

        from app.services import trigger_service  # noqa: PLC0415

        if not trigger_service.owner_is_active(db, trigger):
            _fail_run(db, run, "The organization or user that owns this trigger is deactivated")
            _settle_schedule(db, trigger, run)
            return {"status": "failed"}

        run.status = "running"
        db.commit()
        logger.info("TriggerRun %s started (trigger=%s)", run_id, trigger_id)

        base_model_json = trigger_service.pinned_model_json(db, trigger)
        if base_model_json is None:
            _fail_run(db, run, "Pinned model version not found")
            _settle_schedule(db, trigger, run)
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}

        from app.services.trigger_service import apply_overrides  # noqa: PLC0415

        merged_model = apply_overrides(
            base_model_json,
            override_data or {},
            trigger.override_schema,  # type: ignore[arg-type]
        )

        # 5. Parse merged model into OptimizationProblem before solving
        from app.schemas.optimization import OptimizationProblem  # noqa: PLC0415

        try:
            problem = OptimizationProblem.model_validate(merged_model)
        except Exception as exc:
            logger.warning(
                "OptimizationProblem validation failed for trigger run %s: %s", run_id, exc
            )
            _fail_run(db, run, f"Model validation failed: {exc}")
            _settle_schedule(db, trigger, run)
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}

        # The instance caps every other solve is held to: the variable limit,
        # the time-limit ceiling and the daily quota. Triggered solves skipped
        # all three, so an operator's limits did not apply to anything fired
        # from outside.
        refusal = _instance_cap_refusal(db, trigger, problem)
        if refusal is not None:
            _fail_run(db, run, refusal)
            _settle_schedule(db, trigger, run)
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}
        if time_limit_seconds is not None and time_limit_seconds > 0:
            problem.options.time_limit_seconds = min(
                problem.options.time_limit_seconds, time_limit_seconds
            )
        # The model's own solver. ``SolverService().solve(problem)`` without a
        # name ran every triggered solve on SCIP, whichever solver it chose.
        effective = solver_name or trigger_service.effective_solver(problem)

        from app.domains.solver.services.solver_service import SolverService  # noqa: PLC0415
        from app.shared.core.prometheus_metrics import (  # noqa: PLC0415
            ACTIVE_SOLVES,
            SOLVE_DURATION,
            SOLVE_TOTAL,
        )

        solver = SolverService()
        _solve_start = time.monotonic()
        ACTIVE_SOLVES.inc()
        try:
            result = solver.solve(problem, solver_name=effective)
            _solve_elapsed = time.monotonic() - _solve_start
            SOLVE_DURATION.observe(_solve_elapsed)
            # Always use model_dump() — result is OptimizationResult (Pydantic model), not a dict
            result_data = result.model_dump()
            result_status_val = getattr(
                result.status,
                "value",
                "optimal",
            )
            # A non-raising solver error (e.g. EXPR_PARSE_ERROR) comes back as
            # status=error WITHOUT raising — treat it as a failure, matching
            # /solve and execute_model (ADR-007 S3).
            if result_status_val == "error":
                solve_status = "failed"
                error_msg = getattr(result, "error_message", None) or "Solver returned an error"
            else:
                solve_status = "completed"
                error_msg = None
            SOLVE_TOTAL.labels(
                status=result_status_val,
                generator="trigger",
            ).inc()
        except Exception as exc:
            SOLVE_TOTAL.labels(
                status="error",
                generator="trigger",
            ).inc()
            logger.warning("Solver failed for trigger run %s: %s", run_id, exc)
            solve_status = "failed"
            result_data = None
            error_msg = str(exc)
        finally:
            ACTIVE_SOLVES.dec()

        # 7. Record the run's ModelExecution via the single writer (ADR-007 / P1.5 F0).
        # Build the pending row with the trigger-specific provenance, then let
        # execution_writer apply the terminal transition — so triggers store the SAME
        # canonical ``to_result_data()`` shape as every other execution (instead of a
        # divergent ``model_dump()`` blob whose ``.get("status")`` never matched the
        # canonical ``solver_status`` key) and share the terminal-state guard.
        from app.domains.solver import execution_writer  # noqa: PLC0415
        from app.models import ExecutionStatus  # noqa: PLC0415
        from app.models.optimization_model import ModelExecution  # noqa: PLC0415
        from app.shared.utils.datetime_helpers import utcnow  # noqa: PLC0415

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        now = utcnow()

        execution_id = "exe_" + secrets.token_hex(16)
        model_execution = ModelExecution(
            id=execution_id,
            organization_model_id=None,
            organization_id=trigger.organization_id,
            executed_by_user_id=None,
            input_data={
                **problem.model_dump(mode="json"),
                "trigger_id": trigger.id,
                "trigger_name": trigger.name,
                "override_data": override_data or {},
            },
            status=ExecutionStatus.PENDING.value,
            trigger_id=trigger.id,
            origin="triggered",
            # Provenance: navigates back to the trigger that fired this run.
            source_kind="trigger",
            source_id=trigger.id,
            started_at=start_datetime,
            solver_name=effective,
        )
        db.add(model_execution)
        db.flush()

        if solve_status == "completed":
            # ``result`` is a valid OptimizationResult here (completed ⇒ the solve ran
            # and did not return status=error). The writer sets solver_status,
            # objective_value, result_data and completed_at from it.
            execution_writer.apply_completed(
                model_execution,
                result=result,
                execution_time_seconds=elapsed_ms / 1000.0,
            )
        else:
            execution_writer.apply_failed(
                model_execution, error=error_msg or "Solver returned an error"
            )

        # Link execution back to the TriggerRun. TriggerRun keeps its own result_data
        # shape (its API contract); only the shared ModelExecution row is canonicalized.
        run.execution_id = model_execution.id

        run.status = solve_status
        run.result_data = result_data
        run.error_message = error_msg
        run.execution_time_ms = elapsed_ms
        run.completed_at = now
        _settle_schedule(db, trigger, run)
        db.commit()

        if trigger.created_by:
            try:
                from app.services.notification_service import NotificationService  # noqa: PLC0415

                svc = NotificationService(db=db)
                if solve_status == "completed":
                    svc.notify_execution_completed(
                        user_id=trigger.created_by,
                        organization_id=trigger.organization_id,
                        execution_id=model_execution.id,
                        model_name=trigger.name,
                        objective_value=model_execution.objective_value,
                    )
                else:
                    svc.notify_execution_failed(
                        user_id=trigger.created_by,
                        organization_id=trigger.organization_id,
                        execution_id=model_execution.id,
                        model_name=trigger.name,
                        error=error_msg or "Unknown error",
                    )
                db.commit()
            except Exception as exc:
                logger.warning("Notification failed for trigger run %s: %s", run_id, exc)
                try:
                    db.rollback()
                except Exception:
                    logger.debug("DB rollback failed in notification error handler", exc_info=True)

        event_type = (
            "trigger.execution.completed"
            if solve_status == "completed"
            else "trigger.execution.failed"
        )
        _deliver_webhook(trigger, run, event_type)

        logger.info(
            "TriggerRun %s completed: status=%s elapsed_ms=%d execution_id=%s",
            run_id,
            solve_status,
            elapsed_ms,
            model_execution.id,
        )
        return {"status": solve_status, "run_id": run_id, "execution_id": model_execution.id}

    except Exception as exc:
        logger.exception("Unexpected error in trigger_solve_task for run %s: %s", run_id, exc)
        try:
            db.rollback()
        except Exception:
            logger.debug("DB rollback failed in trigger outer handler", exc_info=True)
        # Mark run as failed if we can
        try:
            from app.models.trigger import TriggerRun  # noqa: PLC0415

            run = db.query(TriggerRun).filter(TriggerRun.id == run_id).first()
            if run:
                _fail_run(db, run, f"Unexpected error: {exc}")
        except Exception:
            logger.debug("Failed to mark trigger run %s as failed", run_id, exc_info=True)
        return {"status": "failed", "error": str(exc)}

    finally:
        db.close()


def _instance_cap_refusal(db: Any, trigger: Any, problem: Any) -> str | None:
    """Why the instance caps refuse this solve, or None. Clamps the time limit in place."""
    from fastapi import HTTPException  # noqa: PLC0415

    from app.models import Organization  # noqa: PLC0415
    from app.services.platform_settings_service import (  # noqa: PLC0415
        PlatformSettingsService as PSS,
    )
    from app.services.solver_comparison_setup import enforce_instance_caps  # noqa: PLC0415
    from app.shared.core.rate_limiter import check_rate_limit  # noqa: PLC0415

    try:
        capped = enforce_instance_caps(db, problem)
    except HTTPException as exc:
        detail = exc.detail
        return detail.get("message") if isinstance(detail, dict) else str(detail)
    problem.options.time_limit_seconds = capped.options.time_limit_seconds

    daily = PSS.get_instance_limits(db)["max_daily_solves"]
    org = db.get(Organization, trigger.organization_id)
    if daily > 0 and org is not None:
        allowed, _info = check_rate_limit(f"solve_daily:{org.id}", daily, daily)
        if not allowed:
            return (
                f"Today's limit of {daily:,} solves has been reached, so this run did "
                f"not solve. It resets tomorrow."
            )
    return None


def _settle_schedule(db: Any, trigger: Any, run: Any) -> None:
    """Count a settled cron run toward its schedule's auto-disable.

    The counter used to move only when the fire itself failed, which for a cron
    fire means a missing required override. A model that failed in the worker
    on every tick reset it to zero on every enqueue, so the schedule never
    disabled itself and "disabled after N consecutive failures" could not
    happen for the reason it describes.
    """
    if getattr(run, "source", None) != "cron":
        return
    from app.models.trigger import TriggerSchedule  # noqa: PLC0415
    from app.tasks.cron_tasks import record_cron_outcome  # noqa: PLC0415

    schedule = db.query(TriggerSchedule).filter(TriggerSchedule.trigger_id == trigger.id).first()
    if schedule is None:
        return
    try:
        record_cron_outcome(db, schedule, trigger, failed=run.status == "failed")
        db.commit()
    except Exception:
        logger.warning("Could not record the cron outcome of run %s", run.id, exc_info=True)
        db.rollback()


def _fail_run(db: Any, run: Any, error: str) -> None:
    """Mark a run as failed with an error message."""
    from app.shared.utils.datetime_helpers import utcnow  # noqa: PLC0415

    run.status = "failed"
    run.error_message = error
    run.completed_at = utcnow()
    try:
        db.commit()
    except Exception as exc:
        logger.error("Failed to persist run failure for %s: %s", run.id, exc)


def _deliver_webhook(
    trigger: Any,
    run: Any,
    event_type: str,
) -> None:
    """Queue the outbound webhook for a trigger run completion."""
    try:
        from app.services.webhook_service import build_webhook_payload  # noqa: PLC0415
        from app.tasks.webhook_tasks import deliver_webhook_task  # noqa: PLC0415

        payload = build_webhook_payload(
            event_type=event_type,
            organization_id=trigger.organization_id,
            data={
                "run_id": run.id,
                "trigger_id": trigger.id,
                "trigger_name": trigger.name,
                "status": run.status,
                "execution_time_ms": run.execution_time_ms,
                "error_message": run.error_message,
                "execution_id": getattr(run, "execution_id", None),
            },
        )
        deliver_webhook_task.apply_async(
            args=[str(trigger.webhook_url), payload, trigger.webhook_secret, run.id],
        )
        logger.debug("Queued webhook %s for trigger run %s", event_type, run.id)
    except Exception as exc:
        logger.warning("Failed to queue webhook for trigger run %s: %s", run.id, exc)
        # Create in-app notification as fallback
        _notify_owner(trigger, run, event_type)


def _notify_owner(trigger: Any, run: Any, event_type: str) -> None:
    """Create an in-app notification when outbound webhook delivery fails."""
    if not getattr(trigger, "created_by", None):
        logger.warning(
            "Webhook delivery failed for trigger run %s but trigger %s has no owner — "
            "cannot create notification (org=%s).",
            run.id,
            trigger.id,
            trigger.organization_id,
        )
        return

    try:
        from app.models import NotificationType  # noqa: PLC0415
        from app.services.notification_service import NotificationService  # noqa: PLC0415

        db = SessionLocal()
        try:
            svc = NotificationService(db)
            svc.create_notification(
                user_id=trigger.created_by,
                organization_id=trigger.organization_id,
                notification_type=NotificationType.SYSTEM,
                title="Webhook delivery failed",
                message=(
                    f"Webhook for trigger '{trigger.name}' (run {run.id}) "
                    f"could not be delivered. Event: {event_type}, status: {run.status}."
                ),
                data={
                    "trigger_id": trigger.id,
                    "run_id": run.id,
                    "event_type": event_type,
                },
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning(
            "Failed to create fallback notification for trigger run %s: %s",
            run.id,
            exc,
        )
