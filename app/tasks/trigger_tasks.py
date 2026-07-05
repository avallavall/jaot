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
    8. Update TriggerRun record (status, result, timing, credits)
    9. Deduct credits from organization
    10. Send in-app notification to trigger creator
    11. Deliver outbound webhook
    12. Close DB session

    Args:
        run_id: TriggerRun PK to update.
        trigger_id: SolveTrigger PK.
        override_data: Override key-value pairs supplied by the caller.

    Returns:
        Dict with run status and summary.
    """
    db = SessionLocal()
    start_time = time.time()
    from app.shared.utils.datetime_helpers import utcnow as _utcnow  # noqa: PLC0415

    start_datetime = _utcnow()
    # ADR-007 S3: track a COMMITTED pre-pay so an UNEXPECTED failure between the
    # deduct and the settle still refunds it. Trigger rows carry no celery_task_id
    # and are inserted terminal, so the execution reaper never backstops them.
    _prepaid_refund = 0
    _prepaid_org_id: str | None = None
    _settled = False

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

        run.status = "running"
        db.commit()
        logger.info("TriggerRun %s started (trigger=%s)", run_id, trigger_id)

        from app.models.builder_document import ModelBuilderDocument  # noqa: PLC0415
        from app.models.model_version import ModelVersion  # noqa: PLC0415

        version = db.query(ModelVersion).filter(ModelVersion.id == trigger.version_id).first()
        if not version:
            _fail_run(db, run, "Pinned model version not found")
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}

        # Use version's model_json if available (pinned at checkpoint time);
        # fall back to the document's model_json for pre-migration versions.
        base_model_json: dict[str, Any] = {}
        if version.model_json:
            base_model_json = dict(version.model_json)
        else:
            # Fallback for pre-migration versions without model_json
            doc = (
                db.query(ModelBuilderDocument)
                .filter(ModelBuilderDocument.id == trigger.document_id)
                .first()
            )
            if doc and doc.model_json:
                base_model_json = dict(doc.model_json)
            elif version.canvas_json:
                # Canvas JSON is not directly solvable but preserve it as context
                base_model_json = {"canvas": version.canvas_json}

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
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}

        # ADR-007 S3: pre-pay BEFORE solving (one credit model). Pool-first when
        # the trigger names a workspace, else org balance; a shortfall fails the
        # run without solving. A solve failure refunds under the idempotent
        # (trigger, run_id) key, so a failed trigger nets to zero. This replaces
        # the old deduct-after-solve, which under-charged: it read credits_used
        # from the result (~0 for a real solve) and swallowed errors.
        from app.domains.solver.pricing import calculate_credits  # noqa: PLC0415
        from app.models import Organization  # noqa: PLC0415
        from app.services.credits_service import (  # noqa: PLC0415
            CreditsService,
            InsufficientCreditsError,
        )

        org = db.query(Organization).filter(Organization.id == trigger.organization_id).first()
        if org is None:
            _fail_run(db, run, "Organization not found")
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}

        base_credits = calculate_credits(problem, solver_name="scip", db=db)
        prepaid_from_pool = False
        try:
            if trigger.workspace_id:
                try:
                    from app.services import workspace_credits_service  # noqa: PLC0415

                    workspace_credits_service.deduct_credits_for_solve(
                        db=db,
                        org=org,
                        workspace_id=trigger.workspace_id,
                        credits_needed=base_credits,
                        reference_id=run_id,
                    )
                    db.commit()
                    prepaid_from_pool = True
                except ValueError:
                    pass  # pool exhausted -> org fallback below
            if not prepaid_from_pool:
                CreditsService.deduct_credits(
                    db=db,
                    organization_id=org.id,
                    credits=base_credits,
                    description=f"Trigger solve pre-pay: {trigger.name} (run {run_id})",
                    reference_type="trigger",
                    reference_id=run_id,
                )
                db.commit()
        except InsufficientCreditsError:
            _fail_run(db, run, "Insufficient credits")
            _deliver_webhook(trigger, run, "trigger.execution.failed")
            return {"status": "failed"}

        # Pre-pay committed — arm the outer-except refund backstop.
        _prepaid_refund = base_credits
        _prepaid_org_id = org.id

        from app.domains.solver.services.solver_service import SolverService  # noqa: PLC0415
        from app.shared.core.prometheus_metrics import (  # noqa: PLC0415
            ACTIVE_SOLVES,
            CREDITS_CONSUMED,
            SOLVE_DURATION,
            SOLVE_TOTAL,
            RefundReason,
        )

        solver = SolverService()
        _solve_start = time.time()
        ACTIVE_SOLVES.inc()
        try:
            result = solver.solve(problem)
            _solve_elapsed = time.time() - _solve_start
            SOLVE_DURATION.observe(_solve_elapsed)
            # Always use model_dump() — result is OptimizationResult (Pydantic model), not a dict
            result_data = result.model_dump()
            result_status_val = getattr(
                result.status,
                "value",
                "optimal",
            )
            # A non-raising solver error (e.g. EXPR_PARSE_ERROR) comes back as
            # status=error WITHOUT raising — treat it as a failure so the prepay
            # is refunded, matching /solve and execute_model (ADR-007 S3). Before
            # this, a trigger charged for an errored solve it recorded as
            # "completed".
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

        # 7. Create ModelExecution row with origin='triggered'
        from app.models.optimization_model import ModelExecution  # noqa: PLC0415
        from app.shared.utils.datetime_helpers import utcnow  # noqa: PLC0415

        elapsed_ms = int((time.time() - start_time) * 1000)
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
            status=solve_status,
            result_data=result_data,
            error_message=error_msg,
            execution_time_ms=elapsed_ms,
            solver_status=(result_data or {}).get("status"),
            objective_value=(result_data or {}).get("objective_value"),
            credits_consumed=(base_credits if solve_status == "completed" else 0),
            trigger_id=trigger.id,
            origin="triggered",
            # Provenance: navigates back to the trigger that fired this run.
            source_kind="trigger",
            source_id=trigger.id,
            started_at=start_datetime,
            completed_at=now,
        )
        db.add(model_execution)
        db.flush()

        # Link execution back to the TriggerRun
        run.execution_id = model_execution.id

        run.status = solve_status
        run.result_data = result_data
        run.error_message = error_msg
        run.execution_time_ms = elapsed_ms
        run.completed_at = now
        db.commit()

        # 9. Settle the pre-paid credits (ADR-007 S3). A completed run keeps the
        #    charge; a failed run refunds it under the idempotent (trigger,
        #    run_id) REFUND key so the failure nets to zero. Best-effort: a
        #    settlement error must not fail the run.
        credits_used = 0
        if solve_status == "completed":
            run.credits_consumed = base_credits
            credits_used = base_credits
            CREDITS_CONSUMED.inc(base_credits)
            db.commit()
        else:
            try:
                CreditsService(db).refund_credits(
                    organization_id=org.id,
                    credits=base_credits,
                    description=(
                        f"{RefundReason.TASK_EXCEPTION.value} "
                        f"(trigger run {run_id}): {(error_msg or 'solve failed')[:200]}"
                    ),
                    reference_type="trigger",
                    reference_id=run_id,
                )
                db.commit()
            except Exception as exc:
                logger.warning("Credit refund failed for trigger run %s: %s", run_id, exc)
                db.rollback()
        # Prepay settled (charge kept on completed / refunded on failed): the
        # outer-except backstop must NOT refund again.
        _settled = True

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
        _deliver_webhook(trigger, run, event_type, credits_used=credits_used)

        logger.info(
            "TriggerRun %s completed: status=%s elapsed_ms=%d credits=%d execution_id=%s",
            run_id,
            solve_status,
            elapsed_ms,
            credits_used,
            model_execution.id,
        )
        return {"status": solve_status, "run_id": run_id, "execution_id": model_execution.id}

    except Exception as exc:
        logger.exception("Unexpected error in trigger_solve_task for run %s: %s", run_id, exc)
        try:
            db.rollback()
        except Exception:
            logger.debug("DB rollback failed in trigger outer handler", exc_info=True)
        # Refund a stranded pre-pay: the deduct committed but the run failed
        # before the settle ran. Idempotent via (org, REFUND, trigger, run_id),
        # so it is safe even if a partial settle already refunded.
        if _prepaid_refund > 0 and _prepaid_org_id and not _settled:
            try:
                from app.services.credits_service import CreditsService  # noqa: PLC0415

                CreditsService(db).refund_credits(
                    organization_id=_prepaid_org_id,
                    credits=_prepaid_refund,
                    description=f"trigger_prepay_stranded (run {run_id}): {str(exc)[:160]}",
                    reference_type="trigger",
                    reference_id=run_id,
                )
                db.commit()
            except Exception:
                logger.warning("Failed to refund stranded trigger prepay for %s", run_id)
                db.rollback()
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
    credits_used: int = 0,
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
                "credits_consumed": credits_used,
                "execution_time_ms": run.execution_time_ms,
                "error_message": run.error_message,
                "execution_id": getattr(run, "execution_id", None),
            },
        )
        deliver_webhook_task.apply_async(
            args=[str(trigger.webhook_url), payload, trigger.webhook_secret],
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
