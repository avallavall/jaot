"""Marketplace catalog endpoints."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, Organization, OrganizationModel, TransactionType, User
from app.schemas.model import (
    ActivateModelRequest,
    ModelCatalogListResponse,
    ModelCatalogResponse,
    OrganizationModelResponse,
)
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.services.featured_placement_service import FeaturedPlacementService
from app.services.notification_service import NotificationService
from app.services.platform_settings_service import PlatformSettingsService
from app.services.seller_analytics_service import SellerAnalyticsService
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.model_helpers import build_org_model_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=ModelCatalogListResponse, operation_id="list_catalog_models")
async def list_catalog_models(
    request: Request,
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Search in name and description"),
    is_official: bool | None = Query(None, description="Filter official models"),
    is_free: bool | None = Query(None, description="Filter free models"),
    min_price: float | None = Query(None, description="Minimum price filter (EUR)"),
    max_price: float | None = Query(None, description="Maximum price filter (EUR)"),
    min_rating: float | None = Query(None, ge=0, le=5, description="Minimum average rating"),
    sort_by: str = Query("popular", pattern="^(popular|newest|price_asc|price_desc|rating)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ModelCatalogListResponse:
    """List models available in the marketplace catalog."""
    query = db.query(ModelCatalog).filter(
        ModelCatalog.status == "published",
        ModelCatalog.is_public == True,  # noqa: E712
    )

    if category:
        query = query.filter(ModelCatalog.category == category)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                ModelCatalog.name.ilike(search_term),
                ModelCatalog.display_name.ilike(search_term),
                ModelCatalog.description.ilike(search_term),
            )
        )

    if is_official is not None:
        query = query.filter(ModelCatalog.is_official == is_official)

    if is_free is not None:
        if is_free:
            query = query.filter(ModelCatalog.price_eur == 0)
        else:
            query = query.filter(ModelCatalog.price_eur > 0)

    if min_price is not None:
        query = query.filter(ModelCatalog.price_eur >= min_price)
    if max_price is not None:
        query = query.filter(ModelCatalog.price_eur <= max_price)
    if min_rating is not None:
        query = query.filter(ModelCatalog.avg_rating >= min_rating)

    # Sorting
    if sort_by == "popular":
        query = query.order_by(ModelCatalog.total_executions.desc())
    elif sort_by == "newest":
        query = query.order_by(ModelCatalog.created_at.desc())
    elif sort_by == "price_asc":
        query = query.order_by(ModelCatalog.price_eur.asc())
    elif sort_by == "price_desc":
        query = query.order_by(ModelCatalog.price_eur.desc())
    elif sort_by == "rating":
        query = query.order_by(ModelCatalog.avg_rating.desc().nullslast())

    total = query.count()
    offset = (page - 1) * page_size
    models = query.offset(offset).limit(page_size).all()

    # Batch pre-fetch organizations to avoid N+1 queries
    org_ids = list({s.author_organization_id for s in models if s.author_organization_id})
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    items = []
    for s in models:
        item = ModelCatalogResponse.model_validate(s)
        if s.author_organization_id:
            author_org = orgs.get(s.author_organization_id)
            if author_org:
                item.author_name = author_org.name
                item.author_verified = author_org.is_verified
        items.append(item)

    # Fire-and-forget: log impressions for returned models
    try:
        if models:
            analytics = SellerAnalyticsService(db)
            model_ids = [m.id for m in models]
            # Catalog list is public -- viewer may not be authenticated
            viewer_user = getattr(request.state, "user", None)
            viewer_org_id = getattr(viewer_user, "organization_id", None) if viewer_user else None
            viewer_ip = request.client.host if request.client else None
            analytics.log_impression(model_ids, viewer_org_id, viewer_ip)
    except Exception:
        logger.debug("Failed to log impressions", exc_info=True)

    return ModelCatalogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/catalog/promoted-ids", operation_id="get_promoted_model_ids")
async def get_promoted_model_ids(
    db: Session = Depends(get_db),
) -> dict[str, list[str]]:
    """Return model IDs with active homepage_carousel placements (public, no auth)."""
    service = FeaturedPlacementService(db)
    placements = service.get_active_placements(placement_type="homepage_carousel")
    model_ids = [p.catalog_model_id for p in placements]
    return {"model_ids": model_ids}


@router.get(
    "/catalog/{model_id}", response_model=ModelCatalogResponse, operation_id="get_catalog_model"
)
async def get_catalog_model(
    request: Request,
    model_id: str,
    db: Session = Depends(get_db),
) -> ModelCatalogResponse:
    """Get details of a specific model in the catalog."""
    model = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.id == model_id,
            ModelCatalog.status == "published",
            ModelCatalog.is_public == True,  # noqa: E712
        )
        .first()
    )

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    response = ModelCatalogResponse.model_validate(model)

    if model.author_organization_id:
        author_org = (
            db.query(Organization).filter(Organization.id == model.author_organization_id).first()
        )
        if author_org:
            response.author_name = author_org.name
            response.author_verified = author_org.is_verified

    # Fire-and-forget: log view event for this model detail page
    try:
        analytics = SellerAnalyticsService(db)
        viewer_user = getattr(request.state, "user", None)
        viewer_org_id = getattr(viewer_user, "organization_id", None) if viewer_user else None
        viewer_ip = request.client.host if request.client else None
        analytics.log_view(model_id, viewer_org_id, viewer_ip)
    except Exception:
        logger.debug("Failed to log view event for %s", model_id, exc_info=True)

    return response


@router.get("/catalog/{model_id}/schema", operation_id="get_catalog_model_schema")
async def get_catalog_model_schema(
    model_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get the input schema and example for a catalog model."""
    model = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.id == model_id,
            ModelCatalog.status == "published",
        )
        .first()
    )

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    return {
        "id": model.id,
        "name": model.name,
        "generator_type": model.generator_type,
        "input_schema": model.input_schema,
        "input_fields": model.input_fields,
        "example_input": model.example_input,
        "scenario_description": model.scenario_description,
    }


@router.post(
    "/catalog/{model_id}/activate",
    response_model=OrganizationModelResponse,
    operation_id="activate_catalog_model",
)
async def activate_catalog_model(
    model_id: str,
    body: ActivateModelRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationModelResponse:
    """Activate a model from the catalog for the user's organization."""
    catalog_model = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.id == model_id,
            ModelCatalog.status == "published",
        )
        .first()
    )

    if not catalog_model:
        raise HTTPException(status_code=404, detail="Model not found")

    existing = (
        db.query(OrganizationModel)
        .filter(
            OrganizationModel.organization_id == current_user.organization_id,
            OrganizationModel.catalog_id == model_id,
            OrganizationModel.is_active == True,  # noqa: E712
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="Model already activated")

    monetization_enabled = PlatformSettingsService.is_monetization_enabled(db)

    # Self-activation block (D-14): only relevant when models are paid — a
    # creator must not "buy" their own model. With monetization off the
    # marketplace is free, so activating your own published model is allowed.
    if (
        monetization_enabled
        and catalog_model.author_organization_id == current_user.organization_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Cannot purchase your own model",
        )

    # A paid activation only happens when monetization is enabled AND the model
    # carries a price. Otherwise the model is free to activate.
    charged = monetization_enabled and catalog_model.price_eur > 0
    if charged:
        credits_needed = int(catalog_model.price_eur * 10)
        service = CreditsService(db)
        try:
            if catalog_model.author_organization_id:
                # Paid marketplace model: commission split
                commission_rate = PlatformSettingsService.get_commission_rate(db)
                service.record_marketplace_sale(
                    seller_organization_id=catalog_model.author_organization_id,
                    buyer_organization_id=current_user.organization_id,
                    model_id=catalog_model.id,
                    credits_price=credits_needed,
                    commission_rate=commission_rate,
                )
            else:
                # Official/no-author model: just deduct, no seller to credit
                service.record_transaction(
                    organization_id=current_user.organization_id,
                    transaction_type=TransactionType.EXECUTION,
                    credits_amount=-credits_needed,
                    description=f"Model activation: {catalog_model.name}",
                    reference_type="model",
                    reference_id=catalog_model.id,
                    created_by="system",
                )
        except InsufficientCreditsError as e:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Insufficient credits. Need {e.credits_needed}, have {e.credits_available}"
                ),
            ) from e

    org_model = OrganizationModel(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        catalog_id=model_id,
        custom_name=body.custom_name,
        is_active=True,
        purchased_at=utcnow() if charged else None,
        purchase_price_eur=catalog_model.price_eur if charged else None,
    )

    db.add(org_model)
    catalog_model.total_activations += 1

    db.commit()
    db.refresh(org_model)

    # Fire-and-forget: log marketplace analytics event (separate from seller analytics)
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        ip_address = request.client.host if request.client else None
        if charged:
            analytics.log_event(
                user_id=current_user.id,
                org_id=current_user.organization_id,
                event_type=evt.MARKETPLACE_PURCHASE,
                ip_address=ip_address,
                metadata={"model_id": model_id, "credits_paid": int(catalog_model.price_eur * 10)},
            )
        else:
            analytics.log_event(
                user_id=current_user.id,
                org_id=current_user.organization_id,
                event_type=evt.MARKETPLACE_ACTIVATE,
                ip_address=ip_address,
                metadata={"model_id": model_id},
            )
        # MCP origin detection: log additional mcp.tool_call event
        if request.url.path.startswith("/mcp"):
            analytics.log_event(
                user_id=current_user.id,
                org_id=current_user.organization_id,
                event_type=evt.MCP_TOOL_CALL,
                ip_address=ip_address,
                metadata={"tool_name": "activate_model"},
            )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    # Notify the creator that their model was activated (fire-and-forget: never
    # block activation). This is an adoption signal — it works in both the free
    # collaborative mode and the paid mode, so the wording stays money-neutral.
    if catalog_model.author_organization_id:
        try:
            seller_users = (
                db.query(User)
                .filter(
                    User.organization_id == catalog_model.author_organization_id,
                    User.is_active == True,  # noqa: E712
                )
                .all()
            )
            notification_svc = NotificationService(db)
            for seller_user in seller_users:
                notification_svc.send_seller_notification(
                    user_id=seller_user.id,
                    organization_id=catalog_model.author_organization_id,
                    event_type="sale",
                    title="Model activated",
                    message=f"Your model '{catalog_model.display_name}' was activated by another team",
                    data={"model_id": catalog_model.id},
                    link="/workspace/credits/seller-analytics",
                )
            db.commit()
        except Exception:
            logger.debug("Failed to send activation notification", exc_info=True)

    return build_org_model_response(org_model)
