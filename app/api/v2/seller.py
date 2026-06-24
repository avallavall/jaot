"""Seller earnings, analytics, placements, verification, notifications, and onboarding API endpoints.

Provides seller-facing endpoints for viewing earnings summary,
detailed sales history with commission breakdown, analytics
dashboards (views, activations, revenue, geo distribution, funnel),
featured placement purchasing, verification badge requests,
notification preference management, and onboarding checklist status.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import (
    CreditTransaction,
    ModelCatalog,
    NotificationPreference,
    Organization,
    TransactionType,
    User,
    Withdrawal,
    WithdrawalSchedule,
    WithdrawalStatus,
)
from app.schemas.featured_placement import (
    ActivePlacementsResponse,
    FeaturedPlacementResponse,
    PlacementPricingResponse,
    PurchasePlacementRequest,
)
from app.schemas.seller import (
    EarningsSummaryResponse,
    NotificationPreferenceEntry,
    NotificationPreferencesResponse,
    OnboardingStatusResponse,
    OnboardingStep,
    SaleRecord,
    SalesHistoryResponse,
    UpdatePreferenceRequest,
)
from app.schemas.seller_analytics import (
    AnalyticsSummaryResponse,
    ConversionFunnelResponse,
    GeoDistributionResponse,
    ModelPerformanceRow,
    TimeSeriesResponse,
)
from app.schemas.verification import VerificationRequestResponse
from app.services.featured_placement_service import FeaturedPlacementService
from app.services.platform_settings_service import PlatformSettingsService
from app.services.seller_analytics_service import SellerAnalyticsService
from app.services.stripe_connect_service import StripeConnectService
from app.services.verification_service import VerificationService
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/seller", tags=["seller"])


@router.get("/earnings/summary", response_model=EarningsSummaryResponse)
async def get_earnings_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EarningsSummaryResponse:
    """Get seller earnings summary for the authenticated user's organization."""
    org_id = current_user.organization_id

    # Total sales count and total earned from SALE_EARNING transactions
    sale_stats = (
        db.query(
            func.count(CreditTransaction.id).label("total_sales"),
            func.coalesce(func.sum(CreditTransaction.credits_amount), 0).label("total_earned"),
        )
        .filter(
            CreditTransaction.organization_id == org_id,
            CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
        )
        .one()
    )

    total_sales: int = sale_stats.total_sales
    total_earned: int = int(sale_stats.total_earned)

    # Total commission from COMMISSION transactions (stored in amount_eur)
    commission_sum = (
        db.query(func.coalesce(func.sum(CreditTransaction.amount_eur), 0.0))
        .filter(
            CreditTransaction.organization_id == org_id,
            CreditTransaction.transaction_type == TransactionType.COMMISSION.value,
        )
        .scalar()
    )
    total_commission: int = int(commission_sum)

    # Withdrawable balance from matured SALE_EARNING minus withdrawals
    from app.services.credits_service import CreditsService

    credits_service = CreditsService(db)
    withdrawable_balance: int = credits_service.get_withdrawable_balance(org_id)

    # Pending maturation: total earned minus withdrawable minus already withdrawn
    total_withdrawn = abs(
        int(
            db.query(func.coalesce(func.sum(CreditTransaction.credits_amount), 0))
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.transaction_type == TransactionType.WITHDRAWAL.value,
            )
            .scalar()
        )
    )
    pending_maturation: int = max(0, total_earned - withdrawable_balance - total_withdrawn)

    # Pending withdrawals
    pending_sum = (
        db.query(func.coalesce(func.sum(Withdrawal.credits_amount), 0))
        .filter(
            Withdrawal.organization_id == org_id,
            Withdrawal.status == WithdrawalStatus.PENDING.value,
        )
        .scalar()
    )
    pending_withdrawals: int = int(pending_sum)

    # Current commission rate
    commission_rate = PlatformSettingsService.get_commission_rate(db)

    return EarningsSummaryResponse(
        total_sales=total_sales,
        total_earned=total_earned,
        total_commission=total_commission,
        withdrawable_balance=withdrawable_balance,
        pending_maturation=pending_maturation,
        pending_withdrawals=pending_withdrawals,
        commission_rate=commission_rate,
    )


@router.get("/earnings/sales", response_model=SalesHistoryResponse)
async def get_sales_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesHistoryResponse:
    """Get detailed sales history with commission breakdown."""
    org_id = current_user.organization_id

    # Total count of SALE_EARNING transactions for this org
    total = (
        db.query(func.count(CreditTransaction.id))
        .filter(
            CreditTransaction.organization_id == org_id,
            CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
        )
        .scalar()
    )

    # Paginated SALE_EARNING transactions
    offset = (page - 1) * page_size
    sale_txns = (
        db.query(CreditTransaction)
        .filter(
            CreditTransaction.organization_id == org_id,
            CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
        )
        .order_by(CreditTransaction.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Batch pre-fetch commission transactions, models, and buyer orgs to avoid N+1
    ref_ids = list({tx.reference_id for tx in sale_txns if tx.reference_id})
    buyer_org_ids = list({tx.buyer_organization_id for tx in sale_txns if tx.buyer_organization_id})

    # Batch fetch COMMISSION transactions keyed by (reference_id, buyer_organization_id)
    commission_txns_raw = (
        (
            db.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.transaction_type == TransactionType.COMMISSION.value,
                CreditTransaction.reference_id.in_(ref_ids),
            )
            .all()
        )
        if ref_ids
        else []
    )
    commission_map: dict[tuple[str | None, str | None], CreditTransaction] = {
        (ct.reference_id, ct.buyer_organization_id): ct for ct in commission_txns_raw
    }

    # Batch fetch models
    models_map = (
        {m.id: m for m in db.query(ModelCatalog).filter(ModelCatalog.id.in_(ref_ids)).all()}
        if ref_ids
        else {}
    )

    # Batch fetch buyer organizations
    buyer_orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(buyer_org_ids)).all()}
        if buyer_org_ids
        else {}
    )

    items: list[SaleRecord] = []
    for tx in sale_txns:
        seller_earning = tx.credits_amount

        commission_tx = commission_map.get((tx.reference_id, tx.buyer_organization_id))
        commission_amount = (
            int(commission_tx.amount_eur) if commission_tx and commission_tx.amount_eur else 0
        )
        credits_price = seller_earning + commission_amount

        catalog = models_map.get(tx.reference_id) if tx.reference_id else None
        model_name = catalog.display_name if catalog else None

        buyer_org = buyer_orgs.get(tx.buyer_organization_id) if tx.buyer_organization_id else None
        buyer_name = buyer_org.name if buyer_org else None

        items.append(
            SaleRecord(
                sale_id=tx.id,
                model_id=tx.reference_id,
                model_name=model_name,
                buyer_organization_name=buyer_name,
                credits_price=credits_price,
                commission_amount=commission_amount,
                seller_earning=seller_earning,
                created_at=tx.created_at,
            )
        )

    return SalesHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Get seller analytics summary: views, impressions, activations, revenue, conversion rate."""
    analytics = SellerAnalyticsService(db)
    return analytics.get_summary(org_id=current_user.organization_id, period=period)


@router.get("/analytics/time-series", response_model=TimeSeriesResponse)
async def get_analytics_time_series(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimeSeriesResponse:
    """Get daily time series of views, impressions, activations, and revenue."""
    analytics = SellerAnalyticsService(db)
    return analytics.get_time_series(org_id=current_user.organization_id, period=period)


@router.get("/analytics/geo", response_model=GeoDistributionResponse)
async def get_analytics_geo(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GeoDistributionResponse:
    """Get geographic distribution of model views by country."""
    analytics = SellerAnalyticsService(db)
    return analytics.get_geo_distribution(org_id=current_user.organization_id, period=period)


@router.get("/analytics/models", response_model=list[ModelPerformanceRow])
async def get_analytics_models(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ModelPerformanceRow]:
    """Get per-model performance comparison for the seller."""
    analytics = SellerAnalyticsService(db)
    return analytics.get_model_performance(org_id=current_user.organization_id, period=period)


@router.get("/analytics/funnel", response_model=ConversionFunnelResponse)
async def get_analytics_funnel(
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversionFunnelResponse:
    """Get conversion funnel: impressions -> views -> activations."""
    analytics = SellerAnalyticsService(db)
    return analytics.get_conversion_funnel(org_id=current_user.organization_id, period=period)


@router.get("/placements/pricing", response_model=list[PlacementPricingResponse])
async def get_placement_pricing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlacementPricingResponse]:
    """Get featured placement pricing tiers for all placement types."""
    service = FeaturedPlacementService(db)
    return service.get_pricing()


@router.post(
    "/placements/purchase",
    response_model=FeaturedPlacementResponse,
    status_code=201,
)
async def purchase_placement(
    body: PurchasePlacementRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FeaturedPlacementResponse:
    """Purchase a featured placement for one of the seller's models.

    Validates model ownership, checks credits, and creates the placement.
    """
    from app.services.credits_service import InsufficientCreditsError

    service = FeaturedPlacementService(db)
    try:
        placement = service.purchase(
            org_id=current_user.organization_id,
            user_id=current_user.id,
            catalog_model_id=body.catalog_model_id,
            placement_type=body.placement_type,
            duration_days=body.duration_days,
        )
    except InsufficientCreditsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "credits_needed": exc.credits_needed,
                "credits_available": exc.credits_available,
            },
        ) from exc
    db.commit()

    # Fire-and-forget: log placement.purchase analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=current_user.id,
            org_id=current_user.organization_id,
            event_type=evt.PLACEMENT_PURCHASE,
            ip_address=request.client.host if request.client else None,
            metadata={
                "placement_type": placement.placement_type,
                "duration_days": placement.duration_days,
            },
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    return FeaturedPlacementResponse(
        id=placement.id,
        catalog_model_id=placement.catalog_model_id,
        placement_type=placement.placement_type,
        status=placement.status,
        credits_paid=placement.credits_paid,
        duration_days=placement.duration_days,
        starts_at=placement.starts_at,
        expires_at=placement.expires_at,
        created_at=placement.created_at,
    )


@router.get("/placements/active", response_model=ActivePlacementsResponse)
async def get_active_placements(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivePlacementsResponse:
    """Get the seller's currently active featured placements."""
    service = FeaturedPlacementService(db)
    placements = service.get_active_placements(org_id=current_user.organization_id)
    items = [
        FeaturedPlacementResponse(
            id=p.id,
            catalog_model_id=p.catalog_model_id,
            placement_type=p.placement_type,
            status=p.status,
            credits_paid=p.credits_paid,
            duration_days=p.duration_days,
            starts_at=p.starts_at,
            expires_at=p.expires_at,
            created_at=p.created_at,
        )
        for p in placements
    ]
    return ActivePlacementsResponse(items=items, total=len(items))


@router.post(
    "/verification/request",
    response_model=VerificationRequestResponse,
    status_code=201,
)
async def request_verification(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VerificationRequestResponse:
    """Submit a verification badge request for the seller's organization.

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
    """Get the current verification request status for the seller's organization.

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


SELLER_EVENT_TYPES = ["sale", "review", "payout", "promotion_expiring"]
NOTIFICATION_CHANNELS = ["in_app", "email"]
# Default preferences: in_app ON, email OFF (missing-row-means-default pattern)
DEFAULT_PREFERENCES: dict[str, bool] = {"in_app": True, "email": False}


@router.get("/notifications/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    """Get notification preferences for the current user.

    Returns all 8 entries (4 event types x 2 channels).
    Missing rows default to in_app=True, email=False.
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
    for event_type in SELLER_EVENT_TYPES:
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
    """Get onboarding checklist status for the current seller.

    Returns 4 steps with completion detection:
    - complete_profile: org has name AND bio filled
    - publish_model: at least 1 published model in catalog
    - add_rich_media: at least 1 published model has logo_url or screenshot_urls
    - setup_payouts: org has credits_earned > 0 OR has a withdrawal schedule
    """
    org_id = current_user.organization_id
    org = db.query(Organization).filter(Organization.id == org_id).first()

    # Step 1: Complete profile - org has name and bio filled
    profile_complete = bool(org and org.name and org.bio and org.bio.strip())

    # Step 2: Publish a model
    published_models = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.author_organization_id == org_id,
            ModelCatalog.status == "published",
        )
        .all()
    )
    has_published = len(published_models) > 0

    # Step 3: Add rich media (logo or screenshots on a published model)
    has_rich_media = any(
        m.logo_url or (hasattr(m, "screenshot_urls") and m.screenshot_urls)
        for m in published_models
    )

    # Step 4: Setup payouts
    has_earnings = bool(org and org.credits_earned > 0)
    has_schedule = (
        (
            db.query(WithdrawalSchedule)
            .filter(WithdrawalSchedule.organization_id == org_id)
            .first()
            is not None
        )
        if not has_earnings
        else False
    )
    payouts_setup = has_earnings or has_schedule

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
        OnboardingStep(
            key="setup_payouts",
            completed=payouts_setup,
            link="/workspace/credits/seller-earnings",
        ),
    ]

    all_complete = all(s.completed for s in steps)
    return OnboardingStatusResponse(steps=steps, all_complete=all_complete)


@router.post("/connect/onboard")
async def start_connect_onboarding(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start or resume Stripe Connect Express onboarding (per D-05).

    Creates a Connect account if needed, then returns an onboarding URL.
    Seller is redirected to Stripe Express to complete KYC.
    """
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeConnectService(db)

    if not org.stripe_connect_account_id:
        service.create_connect_account(org)

    # Generate fresh onboarding link (Pitfall 4: links are single-use)
    base_url = str(request.base_url).rstrip("/")
    onboarding_url = service.create_onboarding_link(
        org=org,
        return_url=f"{base_url}/seller/connect/return",
        refresh_url=f"{base_url}/seller/connect/refresh",
    )

    db.commit()
    return {"onboarding_url": onboarding_url}


@router.get("/connect/status")
async def get_connect_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check Stripe Connect onboarding status."""
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeConnectService(db)
    status = service.get_account_status(org)
    db.commit()
    return status


@router.post("/tos/accept")
async def accept_seller_tos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept the Seller Terms of Service (per D-16).

    Required before first withdrawal, not before publishing.
    """
    service = StripeConnectService(db)
    acceptance = service.accept_seller_tos(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        tos_version="1.0",
    )
    db.commit()
    return {
        "accepted": True,
        "tos_version": acceptance.tos_version,
        "accepted_at": acceptance.accepted_at.isoformat(),
    }


@router.get("/tos/status")
async def get_seller_tos_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check if seller has accepted the current ToS version."""
    service = StripeConnectService(db)
    accepted = service.has_accepted_seller_tos(current_user.organization_id)
    return {"accepted": accepted}
