"""Marketplace catalog endpoints.

ADR-008: the marketplace is free — price filters/sorts, the paid-activation
commission flow and the promoted-placement carousel left with the money layer.
Activation creates the OrganizationModel and notifies the author (adoption
signal), nothing is charged.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, ModelProjectListing, Organization, OrganizationModel, User
from app.schemas.model import (
    ActivateModelRequest,
    ModelCatalogListResponse,
    ModelCatalogResponse,
    OrganizationModelResponse,
)
from app.services.marketplace_fusion import is_fusion_enabled, listing_to_catalog_response
from app.services.notification_service import NotificationService
from app.services.seller_analytics_service import SellerAnalyticsService
from app.shared.db.base import get_db
from app.shared.utils.model_helpers import build_org_model_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=ModelCatalogListResponse, operation_id="list_catalog_models")
async def list_catalog_models(
    request: Request,
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Search in name and description"),
    is_official: bool | None = Query(None, description="Filter official models"),
    min_rating: float | None = Query(None, ge=0, le=5, description="Minimum average rating"),
    sort_by: str = Query("popular", pattern="^(popular|newest|rating)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ModelCatalogListResponse:
    """List models available in the marketplace catalog."""
    # P1.5 cutover: serve from the unified listing facet when the flag is on. The
    # facet shares column names with the catalog, so only the queried class + the
    # id/response mapping differ (ids were preserved by the backfill).
    fusion = is_fusion_enabled(db)
    model_cls = ModelProjectListing if fusion else ModelCatalog

    query = db.query(model_cls).filter(
        model_cls.status == "published",
        model_cls.is_public == True,  # noqa: E712
    )

    if category:
        query = query.filter(model_cls.category == category)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                model_cls.name.ilike(search_term),
                model_cls.display_name.ilike(search_term),
                model_cls.description.ilike(search_term),
            )
        )

    if is_official is not None:
        query = query.filter(model_cls.is_official == is_official)

    if min_rating is not None:
        query = query.filter(model_cls.avg_rating >= min_rating)

    # Sorting
    if sort_by == "popular":
        query = query.order_by(model_cls.total_executions.desc())
    elif sort_by == "newest":
        query = query.order_by(model_cls.created_at.desc())
    elif sort_by == "rating":
        query = query.order_by(model_cls.avg_rating.desc().nullslast())

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
        item = listing_to_catalog_response(s) if fusion else ModelCatalogResponse.model_validate(s)
        if s.author_organization_id:
            author_org = orgs.get(s.author_organization_id)
            if author_org:
                item.author_name = author_org.name
                item.author_verified = author_org.is_verified
        items.append(item)

    # Fire-and-forget: log impressions for returned models (ids preserved → catalog
    # rows still exist, so ModelViewEvent.catalog_model_id stays valid).
    try:
        if models:
            analytics = SellerAnalyticsService(db)
            model_ids = [i.id for i in items]
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


@router.get(
    "/catalog/{model_id}", response_model=ModelCatalogResponse, operation_id="get_catalog_model"
)
async def get_catalog_model(
    request: Request,
    model_id: str,
    db: Session = Depends(get_db),
) -> ModelCatalogResponse:
    """Get details of a specific model in the catalog."""
    fusion = is_fusion_enabled(db)
    if fusion:
        listing = (
            db.query(ModelProjectListing)
            .filter(
                ModelProjectListing.model_project_id == model_id,
                ModelProjectListing.status == "published",
                ModelProjectListing.is_public == True,  # noqa: E712
            )
            .first()
        )
        model = listing
        response = listing_to_catalog_response(listing) if listing else None
    else:
        model = (
            db.query(ModelCatalog)
            .filter(
                ModelCatalog.id == model_id,
                ModelCatalog.status == "published",
                ModelCatalog.is_public == True,  # noqa: E712
            )
            .first()
        )
        response = ModelCatalogResponse.model_validate(model) if model else None

    if not model or response is None:
        raise HTTPException(status_code=404, detail="Model not found")

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
    """Get the input schema and example for a catalog model.

    Requires ``is_public`` (like the detail endpoint): the schema exposes the
    generator + input fields, so a published-but-unlisted model must not leak it.
    """
    if is_fusion_enabled(db):
        listing = (
            db.query(ModelProjectListing)
            .filter(
                ModelProjectListing.model_project_id == model_id,
                ModelProjectListing.status == "published",
                ModelProjectListing.is_public == True,  # noqa: E712
            )
            .first()
        )
        if not listing:
            raise HTTPException(status_code=404, detail="Model not found")
        return {
            "id": listing.model_project_id,
            "name": listing.name,
            "generator_type": listing.generator_type,
            "input_schema": listing.input_schema,
            "input_fields": listing.input_fields,
            "example_input": listing.example_input,
            "scenario_description": listing.scenario_description,
        }

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
    """Activate a model from the catalog for the user's organization (free)."""
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

    org_model = OrganizationModel(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        catalog_id=model_id,
        custom_name=body.custom_name,
        is_active=True,
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
    # block activation). Money-neutral adoption signal (ADR-008).
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
                    event_type="activation",
                    title="Model activated",
                    message=f"Your model '{catalog_model.display_name}' was activated by another team",
                    data={"model_id": catalog_model.id},
                    link="/workspace/models",
                )
            db.commit()
        except Exception:
            logger.debug("Failed to send activation notification", exc_info=True)

    return build_org_model_response(org_model)
