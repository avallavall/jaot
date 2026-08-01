"""Admin marketplace management routes.

Provides admin endpoints for platform-wide author analytics,
per-author drill-down, author leaderboard, feature usage analytics,
and the verification request queue.

ADR-008: promotion (featured placement) management left with the money layer;
author analytics are non-monetary (adoption, not revenue) and no longer gated.
"""

from fastapi import APIRouter, Query, Request

from app.api.deps import DBSession
from app.schemas.analytics import (
    FeatureAnalyticsOverview,
    PaginatedRecentEventsResponse,
)
from app.schemas.author_analytics import (
    AdminAnalyticsResponse,
    AnalyticsSummaryResponse,
)
from app.schemas.common import StatusResponse
from app.schemas.verification import (
    AdminVerificationDecision,
    AdminVerificationEntry,
)
from app.services.analytics_service import AnalyticsService
from app.services.author_analytics_service import AuthorAnalyticsService
from app.services.verification_service import VerificationService

router = APIRouter(prefix="/marketplace", tags=["admin-marketplace"])


@router.get("/author-analytics", response_model=AdminAnalyticsResponse)
def get_admin_author_analytics(
    db: DBSession,
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
) -> AdminAnalyticsResponse:
    """Get platform-wide analytics with the author leaderboard.

    Returns aggregated platform totals (org_id=None) and a ranked list
    of model authors by adoption.
    """
    analytics = AuthorAnalyticsService(db)
    platform_totals = analytics.get_summary(org_id=None, period=period)
    authors = analytics.get_author_leaderboard(period=period)
    return AdminAnalyticsResponse(platform_totals=platform_totals, authors=authors)


@router.get("/author-analytics/{org_id}", response_model=AnalyticsSummaryResponse)
def get_admin_author_detail(
    org_id: str,
    db: DBSession,
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
) -> AnalyticsSummaryResponse:
    """Admin drill-down: get analytics summary for a specific author org."""
    analytics = AuthorAnalyticsService(db)
    return analytics.get_summary(org_id=org_id, period=period)


@router.get("/feature-analytics", response_model=FeatureAnalyticsOverview)
def get_admin_feature_analytics(
    db: DBSession,
    period: str = Query("7d", pattern="^(1h|12h|today|7d|30d|90d|all)$"),
    event_type: str | None = Query(None),
    country_code: str | None = Query(None, max_length=2),
    domain: str | None = Query(None),
    compare: bool = Query(False),
    ts_group: str | None = Query(None, pattern="^(domain|event_type)$"),
) -> FeatureAnalyticsOverview:
    """Get platform-wide feature usage analytics overview.

    Returns KPI summary, event trends, type breakdown, domain
    radar data, conversion funnel, and country distribution.
    Supports optional filters, period-over-period comparison,
    and grouped time series via ts_group.
    """
    analytics = AnalyticsService(db)
    return analytics.get_overview(
        period,
        event_type=event_type,
        country_code=country_code,
        domain=domain,
        compare=compare,
        ts_group=ts_group,
    )


@router.get(
    "/feature-analytics/events",
    response_model=PaginatedRecentEventsResponse,
)
def get_admin_feature_analytics_events(
    db: DBSession,
    period: str = Query("7d", pattern="^(1h|12h|today|7d|30d|90d|all)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: str | None = Query(None),
    country_code: str | None = Query(None, max_length=2),
) -> PaginatedRecentEventsResponse:
    """Get paginated recent analytics events with optional filters."""
    analytics = AnalyticsService(db)
    return analytics.get_recent_events_paginated(
        period,
        page=page,
        page_size=page_size,
        event_type=event_type,
        country_code=country_code,
    )


@router.get("/verification", response_model=list[AdminVerificationEntry])
def get_admin_verification_requests(
    db: DBSession,
) -> list[AdminVerificationEntry]:
    """List all pending verification requests for admin review."""
    service = VerificationService(db)
    return service.get_pending_requests()


@router.post("/verification/{request_id}/decide", response_model=StatusResponse)
def decide_verification(
    request_id: str,
    body: AdminVerificationDecision,
    request: Request,
    db: DBSession,
) -> StatusResponse:
    """Approve or reject a verification request (admin action)."""
    admin_user = getattr(request.state, "user", None)
    admin_user_id = admin_user.id if admin_user else "admin"
    service = VerificationService(db)
    if body.status == "approved":
        service.approve(request_id, admin_user_id, note=body.admin_note, admin_user=admin_user)
    else:
        service.reject(request_id, admin_user_id, note=body.admin_note, admin_user=admin_user)
    db.commit()
    return StatusResponse(status=body.status)
