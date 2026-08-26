"""Celery task for cron-scheduled trigger fires.

Beat calls cron_fire_task at each scheduled tick. The task performs an overlap
pre-check before delegating to the existing fire_trigger() pipeline, ensuring
version pinning is inherited.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.shared.core.celery_app import celery_app
from app.shared.db import SessionLocal

logger = logging.getLogger(__name__)

# Maximum consecutive failures before auto-disabling a schedule
_MAX_CONSECUTIVE_FAILURES = 5


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="app.tasks.cron_tasks.cron_fire_task",
    max_retries=0,
)
def cron_fire_task(self: Any, trigger_id: str) -> dict[str, Any]:
    """Fire a trigger on a cron schedule with pre-checks.

    Steps:
    1. Load trigger and schedule; skip if disabled or missing
    2. Overlap check: skip if previous cron run still active
    3. Fire via existing pipeline (fire_trigger)
    4. Handle success/failure counters
    """
    db = SessionLocal()
    try:
        from app.models.trigger import SolveTrigger, TriggerRun, TriggerSchedule  # noqa: PLC0415
        from app.services import trigger_service  # noqa: PLC0415
        from app.shared.utils.datetime_helpers import utcnow  # noqa: PLC0415

        # 1. Load trigger and schedule
        trigger = db.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
        if not trigger:
            logger.warning("cron_fire_task: trigger %s not found", trigger_id)
            return {"status": "skipped", "reason": "trigger_not_found"}

        schedule = (
            db.query(TriggerSchedule).filter(TriggerSchedule.trigger_id == trigger_id).first()
        )
        if not schedule:
            logger.warning("cron_fire_task: no schedule for trigger %s", trigger_id)
            return {"status": "skipped", "reason": "schedule_not_found"}

        # Beat fires on its own timetable, so this tick is spent whatever happens
        # below. next_run_at has to move with it or the stored value goes stale.
        # Recomputing from the cron expression is idempotent, so doing it once
        # here covers every branch: disabled, overlap-skipped and fired alike.
        # Only the disabled branch used to skip it, and toggling a trigger off
        # is exactly how a schedule ends up sitting there advertising a next run
        # that already passed.
        _update_next_run(schedule)

        if not trigger.is_enabled or not schedule.is_enabled:
            logger.info("cron_fire_task: trigger/schedule disabled for %s", trigger_id)
            db.commit()
            return {"status": "skipped", "reason": "disabled"}

        # 2. Overlap check (CRON-07)
        active_cron_run = (
            db.query(TriggerRun)
            .filter(
                TriggerRun.trigger_id == trigger_id,
                TriggerRun.source == "cron",
                TriggerRun.status.in_(["pending", "running"]),
            )
            .first()
        )
        if active_cron_run:
            run = trigger_service.create_run(db, trigger, None, "skipped_overlap")
            run.source = "cron"
            db.commit()
            logger.info(
                "cron_fire_task: overlap skip for trigger %s (active run %s)",
                trigger_id,
                active_cron_run.id,
            )
            return {"status": "skipped_overlap", "run_id": run.id}

        # 3. Fire via existing pipeline (CRON-08)
        run, error = trigger_service.fire_trigger(db, trigger, None)
        run.source = "cron"

        if error:
            _increment_failure_counter(db, schedule, trigger)
        else:
            # Success: reset failure counter, update timestamps
            schedule.consecutive_failures = 0
            schedule.last_run_at = utcnow()

        db.commit()

        logger.info(
            "cron_fire_task: trigger %s fired, run %s status=%s",
            trigger_id,
            run.id,
            run.status,
        )
        return {"status": run.status, "run_id": run.id}

    except Exception as exc:
        logger.exception("cron_fire_task: unexpected error for trigger %s: %s", trigger_id, exc)
        try:
            db.rollback()
        except Exception:
            logger.debug("DB rollback failed in cron_fire_task error handler", exc_info=True)
        return {"status": "error", "error": str(exc)}

    finally:
        db.close()


def _increment_failure_counter(db: Any, schedule: Any, trigger: Any) -> None:
    """Increment consecutive failure counter and auto-disable after threshold.

    After 5 consecutive failures:
    - Disables the schedule and Beat PeriodicTask
    - Sends trigger.schedule.auto_disabled webhook
    - Creates in-app notification for the trigger creator
    """
    schedule.consecutive_failures += 1
    logger.info(
        "Schedule %s failure count: %d/%d",
        schedule.id,
        schedule.consecutive_failures,
        _MAX_CONSECUTIVE_FAILURES,
    )

    if schedule.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        schedule.is_enabled = False

        # Disable Beat PeriodicTask
        if schedule.beat_task_id:
            try:
                from sqlalchemy_celery_beat.models import (  # noqa: PLC0415
                    PeriodicTask,
                    PeriodicTaskChanged,
                )

                beat_task = db.get(PeriodicTask, schedule.beat_task_id)
                if beat_task:
                    beat_task.enabled = False
                # commit=False, like all three calls in schedule_service. The
                # default is True, and its body is `connection.commit()` on the
                # Session's own connection: the flushed rows become durable
                # without the Session knowing, so after_commit never fires and
                # the db.commit() below raises "This transaction is inactive".
                # The handler then rolls back, which cancels both webhooks this
                # function queued — the auto-disabled notice included.
                PeriodicTaskChanged.update_from_session(db, commit=False)
            except Exception as exc:
                logger.warning(
                    "Failed to disable Beat task for schedule %s: %s",
                    schedule.id,
                    exc,
                )

        try:
            from app.services.webhook_service import build_webhook_payload  # noqa: PLC0415
            from app.shared.db.after_commit import queue_after_commit  # noqa: PLC0415
            from app.tasks.webhook_tasks import deliver_webhook_task  # noqa: PLC0415

            payload = build_webhook_payload(
                event_type="trigger.schedule.auto_disabled",
                organization_id=trigger.organization_id,
                data={
                    "trigger_id": trigger.id,
                    "trigger_name": trigger.name,
                    "schedule_id": schedule.id,
                    "consecutive_failures": schedule.consecutive_failures,
                },
            )
            # On the commit, not here: the caller still has to write
            # is_enabled=False and the failure count, and this webhook announces
            # exactly that. Sent early it could report a schedule as disabled
            # while the transaction that disabled it went on to roll back.
            queue_after_commit(
                db,
                deliver_webhook_task,
                str(trigger.webhook_url),
                payload,
                trigger.webhook_secret,
            )
        except Exception as exc:
            logger.warning(
                "Failed to send auto_disabled webhook for schedule %s: %s",
                schedule.id,
                exc,
            )

        if trigger.created_by:
            try:
                from app.models import NotificationType  # noqa: PLC0415
                from app.services.notification_service import NotificationService  # noqa: PLC0415

                svc = NotificationService(db)
                svc.create_notification(
                    user_id=trigger.created_by,
                    organization_id=trigger.organization_id,
                    notification_type=NotificationType.SYSTEM,
                    title="Schedule auto-disabled",
                    message=(
                        f"The cron schedule for trigger '{trigger.name}' has been "
                        f"auto-disabled after {schedule.consecutive_failures} consecutive "
                        f"failures. Please check your trigger configuration and re-enable "
                        f"the schedule manually."
                    ),
                    data={
                        "trigger_id": trigger.id,
                        "schedule_id": schedule.id,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create auto-disable notification for schedule %s: %s",
                    schedule.id,
                    exc,
                )


def _update_next_run(schedule: Any) -> None:
    """Recompute and store next_run_at for a schedule."""
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        from cronsim import CronSim  # noqa: PLC0415

        tz = ZoneInfo(schedule.timezone)
        now = datetime.now(tz)
        it = CronSim(schedule.cron_expression, now)
        next_run = next(it)
        schedule.next_run_at = next_run.astimezone(timezone.utc)
    except Exception as exc:
        logger.warning(
            "Failed to compute next_run_at for schedule %s: %s",
            schedule.id,
            exc,
        )
