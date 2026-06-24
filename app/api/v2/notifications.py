"""Notification API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import User
from app.services.notification_service import NotificationService
from app.shared.db.base import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    """Response model for a notification."""

    id: str
    type: str
    title: str
    message: str
    data: dict[str, Any] | None = None
    link: str | None = None
    is_read: bool
    created_at: str

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Response model for notification list."""

    items: list[NotificationResponse]
    total: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    """Response model for unread count."""

    unread_count: int


class MarkReadResponse(BaseModel):
    """Response model for mark as read."""

    success: bool
    marked_count: int = 1


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(False, description="Only return unread notifications"),
    limit: int = Query(50, ge=1, le=100, description="Maximum notifications to return"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    """List notifications for the current user, scoped to their organization."""
    service = NotificationService(db)

    notifications = service.get_user_notifications(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        unread_only=unread_only,
        limit=limit,
    )

    unread_count = service.get_unread_count(
        current_user.id, organization_id=current_user.organization_id
    )

    return NotificationListResponse(
        items=[
            NotificationResponse(
                id=n.id,
                type=n.type,
                title=n.title,
                message=n.message,
                data=n.data,
                link=n.link,
                is_read=n.is_read,
                created_at=n.created_at.isoformat(),
            )
            for n in notifications
        ],
        total=len(notifications),
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadCountResponse:
    """Get count of unread notifications scoped to the current user's organization."""
    service = NotificationService(db)
    count = service.get_unread_count(current_user.id, organization_id=current_user.organization_id)
    return UnreadCountResponse(unread_count=count)


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkReadResponse:
    """Mark a specific notification as read (within the current user's organization)."""
    service = NotificationService(db)
    notification = service.mark_as_read(
        notification_id, current_user.id, organization_id=current_user.organization_id
    )

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.commit()
    return MarkReadResponse(success=True)


@router.post("/read-all", response_model=MarkReadResponse)
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkReadResponse:
    """Mark all notifications as read (within the current user's organization)."""
    service = NotificationService(db)
    count = service.mark_all_as_read(current_user.id, organization_id=current_user.organization_id)

    db.commit()
    return MarkReadResponse(success=True, marked_count=count)
