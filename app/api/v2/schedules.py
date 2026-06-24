"""Schedule CRUD and validation endpoints for cron-scheduled trigger fires.

Routes are registered in router.py. Schedule endpoints are nested under
triggers (POST/GET/PATCH/DELETE /triggers/{trigger_id}/schedule). The
standalone validation endpoint is at POST /schedules/validate.

Authentication model:
  - All endpoints require CurrentUser + CurrentOrg via standard auth.
  - Schedule creation enforces tier-based limits.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.models.audit_log import AuditAction
from app.models.trigger import SolveTrigger
from app.schemas.schedule import (
    CronValidationResponse,
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from app.services import schedule_service
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_trigger_or_404(db: DBSession, trigger_id: str, org_id: str) -> SolveTrigger:
    """Fetch a trigger owned by the org or raise 404."""
    trigger = (
        db.query(SolveTrigger)
        .filter(
            SolveTrigger.id == trigger_id,
            SolveTrigger.organization_id == org_id,
        )
        .first()
    )
    if not trigger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trigger not found",
        )
    return trigger


@router.post(
    "/triggers/{trigger_id}/schedule",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cron schedule for a trigger",
)
def create_schedule(
    trigger_id: str,
    body: ScheduleCreateRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> ScheduleResponse:
    """Attach a cron schedule to a trigger (1:1 constraint).

    Validates the cron expression and timezone, checks tier limits,
    and registers the schedule with Celery Beat.
    """
    trigger = _get_trigger_or_404(db, trigger_id, org.id)

    if not trigger.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot schedule a disabled trigger",
        )

    # Check 1:1 constraint
    existing = schedule_service.get_schedule_by_trigger(db, trigger_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trigger already has a schedule",
        )

    # Enforce tier limits
    schedule_service.check_schedule_limit(db, org.id, org.plan)

    # Validate cron expression (raises ValueError on invalid)
    try:
        schedule = schedule_service.create_schedule(
            db, trigger, body.cron_expression, body.timezone
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.TRIGGER_SCHEDULE_CREATE,
        target_type="trigger_schedule",
        target_id=schedule.id,
        target_name=f"Schedule for {trigger.name}",
    )
    db.commit()
    db.refresh(schedule)

    # Fire-and-forget: log schedule.create analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=user.id,
            org_id=org.id,
            event_type=evt.SCHEDULE_CREATE,
            ip_address=request.client.host if request.client else None,
            metadata={"trigger_id": trigger_id, "cron": schedule.cron_expression},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    return ScheduleResponse.model_validate(schedule)


@router.get(
    "/triggers/{trigger_id}/schedule",
    response_model=ScheduleResponse,
    summary="Get the cron schedule for a trigger",
)
def get_schedule(
    trigger_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> ScheduleResponse:
    """Return the schedule attached to a trigger, or 404 if none exists."""
    _get_trigger_or_404(db, trigger_id, org.id)

    schedule = schedule_service.get_schedule_by_trigger(db, trigger_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this trigger",
        )

    return ScheduleResponse.model_validate(schedule)


@router.patch(
    "/triggers/{trigger_id}/schedule",
    response_model=ScheduleResponse,
    summary="Update the cron schedule for a trigger",
)
def update_schedule(
    trigger_id: str,
    body: ScheduleUpdateRequest,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> ScheduleResponse:
    """Update the cron expression, timezone, or enabled state of a schedule."""
    _get_trigger_or_404(db, trigger_id, org.id)

    schedule = schedule_service.get_schedule_by_trigger(db, trigger_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this trigger",
        )

    # If re-enabling, reset consecutive_failures
    if body.is_enabled is True and not schedule.is_enabled:
        schedule.consecutive_failures = 0

    try:
        schedule = schedule_service.update_schedule(
            db,
            schedule,
            cron_expression=body.cron_expression,
            timezone_str=body.timezone,
            is_enabled=body.is_enabled,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.TRIGGER_SCHEDULE_UPDATE,
        target_type="trigger_schedule",
        target_id=schedule.id,
        target_name=f"Schedule for trigger {trigger_id}",
    )
    db.commit()
    db.refresh(schedule)

    return ScheduleResponse.model_validate(schedule)


@router.delete(
    "/triggers/{trigger_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the cron schedule for a trigger",
)
def delete_schedule(
    trigger_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> None:
    """Remove the schedule from a trigger and de-register from Celery Beat."""
    trigger = _get_trigger_or_404(db, trigger_id, org.id)

    schedule = schedule_service.get_schedule_by_trigger(db, trigger_id)
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this trigger",
        )

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.TRIGGER_SCHEDULE_DELETE,
        target_type="trigger_schedule",
        target_id=schedule.id,
        target_name=f"Schedule for {trigger.name}",
    )
    schedule_service.delete_schedule(db, schedule)
    db.commit()

    logger.info("Deleted schedule for trigger %s by user %s", trigger_id, user.id)


@router.post(
    "/schedules/validate",
    response_model=CronValidationResponse,
    summary="Validate a cron expression",
)
def validate_cron(
    body: ScheduleCreateRequest,
    user: CurrentUser,
) -> CronValidationResponse:
    """Validate a cron expression and return the next 3 run times.

    Does not require a trigger -- useful for preview in the UI.
    """
    try:
        result = schedule_service.validate_cron_expression(body.cron_expression, body.timezone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    return CronValidationResponse(
        valid=result["valid"],
        next_runs=result["next_runs"],
    )
