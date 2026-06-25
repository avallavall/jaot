"""Admin marketplace management routes.

Provides admin endpoints for platform-wide seller analytics,
per-seller drill-down, seller leaderboard, promotion management,
and verification request queue.
"""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_monetization_enabled
from app.models.optimization_model import ModelCatalog
from app.models.organization import Organization
from app.schemas.analytics import (
    FeatureAnalyticsOverview,
    PaginatedRecentEventsResponse,
)
from app.schemas.featured_placement import AdminPlacementResponse
from app.schemas.seller_analytics import (
    AdminAnalyticsResponse,
    AnalyticsSummaryResponse,
)
from app.schemas.verification import (
    AdminVerificationDecision,
    AdminVerificationEntry,
)
from app.services.analytics_service import AnalyticsService
from app.services.featured_placement_service import FeaturedPlacementService
from app.services.seller_analytics_service import SellerAnalyticsService
from app.services.verification_service import VerificationService
from app.shared.db.base import get_db

router = APIRouter(prefix="/marketplace", tags=["admin-marketplace"])


@router.get(
    "/seller-analytics",
    response_model=AdminAnalyticsResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def get_admin_seller_analytics(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
) -> AdminAnalyticsResponse:
    """Get platform-wide analytics with seller leaderboard.

    Returns aggregated platform totals (org_id=None) and a ranked list
    of sellers by revenue.
    """
    analytics = SellerAnalyticsService(db)
    platform_totals = analytics.get_summary(org_id=None, period=period)
    sellers = analytics.get_seller_leaderboard(period=period)
    return AdminAnalyticsResponse(platform_totals=platform_totals, sellers=sellers)


@router.get(
    "/seller-analytics/{org_id}",
    response_model=AnalyticsSummaryResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def get_admin_seller_detail(
    org_id: str,
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Admin drill-down: get analytics summary for a specific seller."""
    analytics = SellerAnalyticsService(db)
    return analytics.get_summary(org_id=org_id, period=period)


@router.get("/feature-analytics", response_model=FeatureAnalyticsOverview)
async def get_admin_feature_analytics(
    period: str = Query("7d", pattern="^(1h|12h|today|7d|30d|90d|all)$"),
    event_type: str | None = Query(None),
    country_code: str | None = Query(None, max_length=2),
    domain: str | None = Query(None),
    compare: bool = Query(False),
    ts_group: str | None = Query(None, pattern="^(domain|event_type)$"),
    db: Session = Depends(get_db),
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
async def get_admin_feature_analytics_events(
    period: str = Query("7d", pattern="^(1h|12h|today|7d|30d|90d|all)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: str | None = Query(None),
    country_code: str | None = Query(None, max_length=2),
    db: Session = Depends(get_db),
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


@router.get(
    "/promotions",
    response_model=list[AdminPlacementResponse],
    dependencies=[Depends(require_monetization_enabled)],
)
async def get_admin_promotions(
    db: Session = Depends(get_db),
) -> list[AdminPlacementResponse]:
    """List all active and recent placements with org/model names."""
    service = FeaturedPlacementService(db)
    placements = service.get_active_placements(org_id=None)

    # Batch pre-fetch organizations and models to avoid N+1 queries
    org_ids = list({p.organization_id for p in placements if p.organization_id})
    model_ids = list({p.catalog_model_id for p in placements if p.catalog_model_id})
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )
    catalog_models = (
        {m.id: m for m in db.query(ModelCatalog).filter(ModelCatalog.id.in_(model_ids)).all()}
        if model_ids
        else {}
    )

    result: list[AdminPlacementResponse] = []
    for p in placements:
        org = orgs.get(p.organization_id)
        model = catalog_models.get(p.catalog_model_id)
        result.append(
            AdminPlacementResponse(
                id=p.id,
                catalog_model_id=p.catalog_model_id,
                placement_type=p.placement_type,
                status=p.status,
                credits_paid=p.credits_paid,
                duration_days=p.duration_days,
                starts_at=p.starts_at,
                expires_at=p.expires_at,
                created_at=p.created_at,
                org_name=org.name if org else None,
                model_name=model.display_name if model else None,
                revoked_at=p.revoked_at,
                revoked_by=p.revoked_by,
            )
        )
    return result


@router.post(
    "/promotions/{placement_id}/revoke",
    status_code=204,
    dependencies=[Depends(require_monetization_enabled)],
)
async def revoke_promotion(
    placement_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Revoke an active placement (admin action)."""
    admin_user = getattr(request.state, "user", None)
    admin_user_id = admin_user.id if admin_user else "admin"
    service = FeaturedPlacementService(db)
    service.revoke(placement_id, admin_user_id, admin_user=admin_user)
    db.commit()


class ExtendPlacementRequest(BaseModel):
    """Request body for extending a placement."""

    extra_days: int


@router.post(
    "/promotions/{placement_id}/extend",
    dependencies=[Depends(require_monetization_enabled)],
)
async def extend_promotion(
    placement_id: str,
    body: ExtendPlacementRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Extend a placement's expiration (admin action)."""
    admin_user = getattr(request.state, "user", None)
    admin_user_id = admin_user.id if admin_user else "admin"
    service = FeaturedPlacementService(db)
    service.extend(placement_id, body.extra_days, admin_user_id)
    db.commit()
    return {"status": "extended"}


@router.get("/verification", response_model=list[AdminVerificationEntry])
async def get_admin_verification_requests(
    db: Session = Depends(get_db),
) -> list[AdminVerificationEntry]:
    """List all pending verification requests for admin review."""
    service = VerificationService(db)
    return service.get_pending_requests()


@router.post("/verification/{request_id}/decide")
async def decide_verification(
    request_id: str,
    body: AdminVerificationDecision,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Approve or reject a verification request (admin action)."""
    admin_user = getattr(request.state, "user", None)
    admin_user_id = admin_user.id if admin_user else "admin"
    service = VerificationService(db)
    if body.status == "approved":
        service.approve(request_id, admin_user_id, note=body.admin_note, admin_user=admin_user)
    else:
        service.reject(request_id, admin_user_id, note=body.admin_note, admin_user=admin_user)
    db.commit()
    return {"status": body.status}
