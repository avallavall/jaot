"""Marketplace catalog endpoints.

ADR-008: the marketplace is free — price filters/sorts, the paid-activation
commission flow and the promoted-placement carousel left with the money layer.
P1.5 fusion: the legacy "activate" flow is retired — using a marketplace model
means seeding a fork ModelProject via ``POST /projects/from-marketplace/{id}``
(the adoption signal + activation counter live there now).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import ModelProjectListing, Organization
from app.schemas.model import (
    ModelCatalogListResponse,
    ModelCatalogResponse,
)
from app.services.author_analytics_service import AuthorAnalyticsService
from app.services.marketplace_fusion import listing_to_catalog_response
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=ModelCatalogListResponse, operation_id="list_catalog_models")
def list_catalog_models(
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
    # P1.5 fusion: the marketplace serves from the unified ModelProjectListing facet
    # (the model content lives on the project/version; the listing is its presentation).
    model_cls = ModelProjectListing

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
        item = listing_to_catalog_response(s)
        if s.author_organization_id:
            author_org = orgs.get(s.author_organization_id)
            if author_org:
                item.author_name = author_org.name
                item.author_verified = author_org.is_verified
        items.append(item)

    # Fire-and-forget: log impressions for the returned listings (keyed by their
    # model_project_id — the marketplace identity).
    try:
        if models:
            analytics = AuthorAnalyticsService(db)
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
def get_catalog_model(
    request: Request,
    model_id: str,
    db: Session = Depends(get_db),
) -> ModelCatalogResponse:
    """Get details of a specific model in the catalog."""
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

    response = listing_to_catalog_response(listing)

    if listing.author_organization_id:
        author_org = (
            db.query(Organization).filter(Organization.id == listing.author_organization_id).first()
        )
        if author_org:
            response.author_name = author_org.name
            response.author_verified = author_org.is_verified

    # Fire-and-forget: log view event for this model detail page
    try:
        analytics = AuthorAnalyticsService(db)
        viewer_user = getattr(request.state, "user", None)
        viewer_org_id = getattr(viewer_user, "organization_id", None) if viewer_user else None
        viewer_ip = request.client.host if request.client else None
        analytics.log_view(model_id, viewer_org_id, viewer_ip)
    except Exception:
        logger.debug("Failed to log view event for %s", model_id, exc_info=True)

    return response


@router.get("/catalog/{model_id}/schema", operation_id="get_catalog_model_schema")
def get_catalog_model_schema(
    model_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get the input schema and example for a catalog model.

    Requires ``is_public`` (like the detail endpoint): the schema exposes the
    generator + input fields, so a published-but-unlisted model must not leak it.
    """
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
