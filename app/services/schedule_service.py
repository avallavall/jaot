"""Schedule service -- CRUD for cron schedules with Beat sync.

Manages TriggerSchedule records and their corresponding sqlalchemy-celery-beat
PeriodicTask entries. Follows the caller-commits pattern (no db.commit()).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.trigger import SolveTrigger, TriggerSchedule
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Minimum interval between cron runs: 60 minutes
_MIN_INTERVAL_MINUTES = 60


def validate_cron_expression(expression: str, timezone_str: str = "UTC") -> dict[str, Any]:
    """Validate a cron expression and return next run times.

    Args:
        expression: Standard 5-field cron expression (minute hour dom month dow).
        timezone_str: IANA timezone name (e.g. "America/New_York").

    Returns:
        {"valid": True, "next_runs": [iso_strings_of_next_3_runs]}

    Raises:
        ValueError: If expression or timezone is invalid, or fires too frequently.
    """
    from cronsim import CronSim  # noqa: PLC0415
    from cronsim.cronsim import CronSimError  # noqa: PLC0415

    try:
        tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: {timezone_str}") from None

    try:
        now = datetime.now(tz)
        it = CronSim(expression, now)
    except (ValueError, KeyError, CronSimError) as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from None

    next_runs = []
    for _ in range(3):
        try:
            next_dt = next(it)
            next_runs.append(next_dt.isoformat())
        except StopIteration:
            break

    # Validate minimum interval (must not fire more than once per hour)
    if len(next_runs) >= 2:
        from datetime import datetime as dt_cls

        t1 = dt_cls.fromisoformat(next_runs[0])
        t2 = dt_cls.fromisoformat(next_runs[1])
        diff_minutes = (t2 - t1).total_seconds() / 60
        if diff_minutes < _MIN_INTERVAL_MINUTES:
            raise ValueError(
                f"Schedule fires too frequently ({int(diff_minutes)} min interval). "
                f"Minimum interval is {_MIN_INTERVAL_MINUTES} minutes."
            )

    return {"valid": True, "next_runs": next_runs}


def check_schedule_limit(db: Session, org_id: str, plan_name: str) -> None:
    """Enforce tier-based schedule creation limits.

    Raises HTTPException(403) if cron scheduling is not available on the plan
    or the schedule limit has been reached.
    """
    from app.services.platform_settings_service import PlatformSettingsService as PSS

    plan_config = PSS.get_plan_config_dynamic(db, plan_name)

    current_count = (
        db.query(TriggerSchedule).filter(TriggerSchedule.organization_id == org_id).count()
    )
    max_schedules = plan_config["max_cron_schedules"]
    if current_count >= max_schedules:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Schedule limit reached ({max_schedules})",
        )


def create_schedule(
    db: Session,
    trigger: SolveTrigger,
    cron_expression: str,
    timezone_str: str = "UTC",
) -> TriggerSchedule:
    """Create a TriggerSchedule and register it with Celery Beat.

    Validates the cron expression, creates the Beat PeriodicTask, and
    computes next_run_at. Does NOT commit -- caller commits.
    """
    from cronsim import CronSim  # noqa: PLC0415

    validate_cron_expression(cron_expression, timezone_str)

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5 cron fields, got {len(parts)}")
    minute, hour, day_of_month, month_of_year, day_of_week = parts

    beat_task_id = None
    try:
        from sqlalchemy_celery_beat.models import (  # noqa: PLC0415
            CrontabSchedule,
            PeriodicTask,
            PeriodicTaskChanged,
        )

        crontab = CrontabSchedule(
            minute=minute,
            hour=hour,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            month_of_year=month_of_year,
            timezone=timezone_str,
        )
        db.add(crontab)
        db.flush()

        beat_task = PeriodicTask(
            name=f"cron_trigger_{trigger.id}",
            task="app.tasks.cron_tasks.cron_fire_task",
            schedule_model=crontab,
            args=json.dumps([trigger.id]),
            enabled=True,
        )
        db.add(beat_task)
        db.flush()
        beat_task_id = beat_task.id

        PeriodicTaskChanged.update_from_session(db, commit=False)
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to register Beat task for trigger %s: %s", trigger.id, exc)

    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)
    it = CronSim(cron_expression, now)
    try:
        next_run = next(it)
        # Convert to UTC for storage
        next_run_utc = next_run.astimezone(timezone.utc).replace(tzinfo=None)
    except StopIteration:
        next_run_utc = None

    schedule = TriggerSchedule(
        id=generate_id("tsch_"),
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        cron_expression=cron_expression,
        timezone=timezone_str,
        is_enabled=True,
        consecutive_failures=0,
        next_run_at=next_run_utc,
        beat_task_id=beat_task_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(schedule)
    db.flush()

    logger.info(
        "Created schedule %s for trigger %s (cron=%s, tz=%s)",
        schedule.id,
        trigger.id,
        cron_expression,
        timezone_str,
    )
    return schedule


def update_schedule(
    db: Session,
    schedule: TriggerSchedule,
    cron_expression: str | None = None,
    timezone_str: str | None = None,
    is_enabled: bool | None = None,
) -> TriggerSchedule:
    """Update a TriggerSchedule and sync changes to Beat.

    Only updates fields that are not None. Does NOT commit.
    """
    from cronsim import CronSim  # noqa: PLC0415

    expression_changed = False

    if cron_expression is not None and cron_expression != schedule.cron_expression:
        tz_to_validate = timezone_str or schedule.timezone
        validate_cron_expression(cron_expression, tz_to_validate)
        schedule.cron_expression = cron_expression
        expression_changed = True

    if timezone_str is not None and timezone_str != schedule.timezone:
        expr_to_validate = cron_expression or schedule.cron_expression
        validate_cron_expression(expr_to_validate, timezone_str)
        schedule.timezone = timezone_str
        expression_changed = True

    if is_enabled is not None:
        schedule.is_enabled = is_enabled

    schedule.updated_at = utcnow()

    # Sync with Beat
    try:
        from sqlalchemy_celery_beat.models import (  # noqa: PLC0415
            PeriodicTask,
            PeriodicTaskChanged,
        )

        if schedule.beat_task_id:
            beat_task = db.query(PeriodicTask).get(schedule.beat_task_id)
            if beat_task:
                if is_enabled is not None:
                    beat_task.enabled = is_enabled

                if expression_changed and beat_task.schedule_model:
                    parts = schedule.cron_expression.strip().split()
                    crontab = beat_task.schedule_model
                    crontab.minute = parts[0]
                    crontab.hour = parts[1]
                    crontab.day_of_month = parts[2]
                    crontab.month_of_year = parts[3]
                    crontab.day_of_week = parts[4]
                    crontab.timezone = schedule.timezone

                PeriodicTaskChanged.update_from_session(db, commit=False)
    except Exception as exc:
        logger.warning("Failed to sync Beat task for schedule %s: %s", schedule.id, exc)
        db.rollback()

    # Recompute next_run_at if expression/timezone changed
    if expression_changed:
        try:
            tz = ZoneInfo(schedule.timezone)
            now = datetime.now(tz)
            it = CronSim(schedule.cron_expression, now)
            next_run = next(it)
            schedule.next_run_at = next_run.astimezone(timezone.utc).replace(tzinfo=None)
        except (StopIteration, Exception):
            schedule.next_run_at = None

    return schedule


def delete_schedule(db: Session, schedule: TriggerSchedule) -> None:
    """Delete a TriggerSchedule and its Beat PeriodicTask.

    Does NOT commit -- caller commits.
    """
    if schedule.beat_task_id:
        try:
            from sqlalchemy_celery_beat.models import (  # noqa: PLC0415
                PeriodicTask,
                PeriodicTaskChanged,
            )

            beat_task = db.query(PeriodicTask).get(schedule.beat_task_id)
            if beat_task:
                db.delete(beat_task)
            PeriodicTaskChanged.update_from_session(db, commit=False)
        except Exception as exc:
            logger.warning("Failed to remove Beat task for schedule %s: %s", schedule.id, exc)
            db.rollback()

    db.delete(schedule)
    logger.info("Deleted schedule %s for trigger %s", schedule.id, schedule.trigger_id)


def get_schedule_by_trigger(db: Session, trigger_id: str) -> TriggerSchedule | None:
    """Get the schedule for a trigger (1:1 relationship)."""
    return db.query(TriggerSchedule).filter(TriggerSchedule.trigger_id == trigger_id).first()
