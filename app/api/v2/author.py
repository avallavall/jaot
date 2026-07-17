"""Author analytics, verification, notifications, and onboarding API endpoints.

P1.5 G8: selling no longer exists — these are AUTHOR-facing endpoints (authors
publish/share models; adoption, not sales). The /seller/* wire paths and tag are
legacy and get renamed in the contract release.

Provides author-facing endpoints for analytics dashboards (views, impressions,
activations, geo distribution, funnel), verification badge requests,
notification preference management, and onboarding checklist status.

ADR-008: the earnings/sales and featured-placement endpoints were removed with
the money layer; analytics metrics are non-monetary (an "activation" is another
org adopting the model, not a sale).
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelProjectListing, NotificationPreference, Organization, User
from app.schemas.author import (
    NotificationPreferenceEntry,
    NotificationPreferencesResponse,
    OnboardingStatusResponse,
    OnboardingStep,
    UpdatePreferenceRequest,
)
from app.schemas.author_analytics import (
    AnalyticsSummaryResponse,
    ConversionFunnelResponse,
    GeoDistributionResponse,
    ModelPerformanceRow,
    TimeSeriesResponse,
)
from app.schemas.verification import VerificationRequestResponse
from app.services.author_analytics_service import AuthorAnalyticsService
from app.services.verification_service import VerificationService
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

# Legacy wire prefix — renamed to /author in the contract release.
router = APIRouter(prefix="/seller", tags=["seller"])


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Get author analytics summary: views, impressions, activations, conversion rate."""
    analytics = AuthorAnalyticsService(db)
    return analytics.get_summary(org_id=current_user.organization_id, period=period)


@router.get("/analytics/time-series", response_model=TimeSeriesResponse)
async def get_analytics_time_series(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimeSeriesResponse:
    """Get daily time series of views, impressions, and activations."""
    analytics = AuthorAnalyticsService(db)
    return analytics.get_time_series(org_id=current_user.organization_id, period=period)


@router.get("/analytics/geo", response_model=GeoDistributionResponse)
async def get_analytics_geo(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GeoDistributionResponse:
    """Get geographic distribution of model views by country."""
    analytics = AuthorAnalyticsService(db)
    return analytics.get_geo_distribution(org_id=current_user.organization_id, period=period)


@router.get("/analytics/models", response_model=list[ModelPerformanceRow])
async def get_analytics_models(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ModelPerformanceRow]:
    """Get per-model performance comparison for the author."""
    analytics = AuthorAnalyticsService(db)
    return analytics.get_model_performance(org_id=current_user.organization_id, period=period)


@router.get("/analytics/funnel", response_model=ConversionFunnelResponse)
async def get_analytics_funnel(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversionFunnelResponse:
    """Get conversion funnel: impressions -> views -> activations."""
    analytics = AuthorAnalyticsService(db)
    return analytics.get_conversion_funnel(org_id=current_user.organization_id, period=period)


@router.post(
    "/verification/request",
    response_model=VerificationRequestResponse,
    status_code=201,
)
async def request_verification(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VerificationRequestResponse:
    """Submit a verification badge request for the author's organization.

    Returns 409 if a request is already pending or approved.
    """
    service = VerificationService(db)
    req = service.request_verification(
        org_id=current_user.organization_id,
        user_id=current_user.id,
    )
    db.commit()
    return VerificationRequestResponse(
        id=req.id,
        organization_id=req.organization_id,
        status=req.status,
        admin_note=req.admin_note,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
    )


@router.get(
    "/verification/status",
    response_model=VerificationRequestResponse | None,
)
async def get_verification_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VerificationRequestResponse | None:
    """Get the current verification request status for the author's organization.

    Returns null if no verification request exists.
    """
    service = VerificationService(db)
    req = service.get_request_for_org(org_id=current_user.organization_id)
    if req is None:
        return None
    return VerificationRequestResponse(
        id=req.id,
        organization_id=req.organization_id,
        status=req.status,
        admin_note=req.admin_note,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
    )


# ADR-008: "sale"/"payout"/"promotion_expiring" notification events left with the
# money layer; reviews and the money-neutral adoption signal remain.
AUTHOR_EVENT_TYPES = ["review", "activation"]
NOTIFICATION_CHANNELS = ["in_app", "email"]
# Default preferences: in_app ON, email OFF (missing-row-means-default pattern)
DEFAULT_PREFERENCES: dict[str, bool] = {"in_app": True, "email": False}


@router.get("/notifications/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    """Get notification preferences for the current user.

    Returns one entry per event type x channel; missing rows default to
    in_app=True, email=False.
    """
    existing = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == current_user.id)
        .all()
    )
    lookup: dict[tuple[str, str], bool] = {
        (pref.event_type, pref.channel): pref.enabled for pref in existing
    }

    entries: list[NotificationPreferenceEntry] = []
    for event_type in AUTHOR_EVENT_TYPES:
        for channel in NOTIFICATION_CHANNELS:
            enabled = lookup.get((event_type, channel), DEFAULT_PREFERENCES[channel])
            entries.append(
                NotificationPreferenceEntry(event_type=event_type, channel=channel, enabled=enabled)
            )

    return NotificationPreferencesResponse(preferences=entries)


@router.put("/notifications/preferences", response_model=NotificationPreferencesResponse)
async def update_notification_preference(
    body: UpdatePreferenceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    """Update a single notification preference toggle.

    Upserts: creates if missing, updates if exists.
    Returns the full updated preferences list.
    """
    existing = (
        db.query(NotificationPreference)
        .filter(
            NotificationPreference.user_id == current_user.id,
            NotificationPreference.event_type == body.event_type,
            NotificationPreference.channel == body.channel,
        )
        .first()
    )

    if existing:
        existing.enabled = body.enabled
    else:
        pref = NotificationPreference(
            user_id=current_user.id,
            event_type=body.event_type,
            channel=body.channel,
            enabled=body.enabled,
        )
        db.add(pref)

    db.commit()

    return await get_notification_preferences(current_user=current_user, db=db)


@router.get("/onboarding/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingStatusResponse:
    """Get onboarding checklist status for the current creator.

    Returns 3 steps with completion detection:
    - complete_profile: org has name AND bio filled
    - publish_model: at least 1 published model in catalog
    - add_rich_media: at least 1 published model has logo_url or screenshot_urls
    """
    org_id = current_user.organization_id
    org = db.query(Organization).filter(Organization.id == org_id).first()

    # Step 1: Complete profile - org has name and bio filled
    profile_complete = bool(org and org.name and org.bio and org.bio.strip())

    # Step 2: Publish a model (a published marketplace listing)
    published_models = (
        db.query(ModelProjectListing)
        .filter(
            ModelProjectListing.author_organization_id == org_id,
            ModelProjectListing.status == "published",
        )
        .all()
    )
    has_published = len(published_models) > 0

    # Step 3: Add rich media (logo or screenshots on a published listing)
    has_rich_media = any(m.logo_url or m.screenshot_urls for m in published_models)

    steps = [
        OnboardingStep(
            key="complete_profile",
            completed=profile_complete,
            link="/workspace/settings",
        ),
        OnboardingStep(
            key="publish_model",
            completed=has_published,
            link="/workspace/models/publish",
        ),
        OnboardingStep(
            key="add_rich_media",
            completed=has_rich_media,
            link="/workspace/models",
        ),
    ]

    all_complete = all(s.completed for s in steps)
    return OnboardingStatusResponse(steps=steps, all_complete=all_complete)
