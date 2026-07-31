"""Marketplace catalog endpoints.

ADR-008: the marketplace is free — price filters/sorts, the paid-activation
commission flow and the promoted-placement carousel left with the money layer.
P1.5 fusion: the legacy "activate" flow is retired — using a marketplace model
means seeding a fork ModelProject via ``POST /projects/from-marketplace/{id}``
(the adoption signal + activation counter live there now).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import OptionalCurrentUser
from app.models import ModelProjectListing, Organization, User
from app.schemas.model import (
    CatalogModelSchemaResponse,
    ModelCatalogListResponse,
    ModelCatalogResponse,
)
from app.services import favorites_service
from app.services.author_analytics_service import AuthorAnalyticsService
from app.services.marketplace_fusion import MARKETPLACE_VISIBLE, listing_to_catalog_response
from app.shared.db.base import get_db
from app.shared.utils.request_helpers import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])


def _record_impressions(
    db: Session, request: Request, viewer: User | None, model_ids: list[str]
) -> None:
    """Store one impression per listing this page returned.

    Telemetry must never cost the reader their page, so a failure here is
    swallowed. The commit is the part that matters: ``get_db`` does not commit,
    so a flush on its own is discarded when the session closes — which is
    exactly how these events came to be recorded and never stored.

    Internal callers are not readers (see ``_is_own_traffic``): this endpoint is
    what the sitemap generator walks, and it walked the whole catalogue hourly.
    """
    if not model_ids or _is_own_traffic(request):
        return
    try:
        with db.begin_nested():
            AuthorAnalyticsService(db).log_impression(
                model_ids,
                viewer.organization_id if viewer else None,
                get_client_ip(request),
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("Failed to log impressions", exc_info=True)


#: Set by our own server-side fetches (``SSR_REQUEST_HEADERS`` in
#: ``frontend/src/lib/seo/ssrFetch.ts`` and the sitemap walk).
_SSR_HEADER = "x-jaot-ssr"


def _is_own_traffic(request: Request) -> bool:
    """True when the caller is one of our own server-side fetches, not a reader.

    Both writers below record a person looking at a listing, and both were
    counting requests no person made:

    * ``sitemap.ts`` pages the whole catalogue every hour (``revalidate: 3600``)
      to build the SEO sitemap — 103 impressions per hour on the reference
      install, 97.8% of every impression ever stored.
    * the model detail page fetches this same endpoint server-side to fill its
      metadata and JSON-LD, so each visit was counted twice: once as a phantom
      view with no country and no organisation, once for real from the browser.

    **The caller declares itself, we do not infer it.** Inferring looked cheaper —
    ``is_trusted_internal_request`` already identifies internal traffic for the
    anonymous rate limit — but Next's ``/api/*`` rewrite proxy forwards only
    ``x-forwarded-host``, never ``X-Forwarded-For``. On any deployment where the
    browser reaches the API *through* Next (the default compose; any self-host
    without Caddy routing ``/api`` itself) a genuine reader arrives from the
    frontend container with no forwarding header at all, so inference would have
    dropped every real view and impression — and with them the "recently opened"
    row, which had just been fixed.

    Forging this header buys nothing: it only removes you from an author's view
    counts. Rate limiting does not read it.
    """
    return _SSR_HEADER in request.headers


def _record_visit(db: Session, request: Request, viewer: User | None, model_id: str) -> None:
    """Store the view event, and the opener's "recently opened" entry.

    Same commit note as :func:`_record_impressions`. The recent entry is per
    user and the catalog is public, so it is only written when the request
    carried credentials the middleware could resolve. Both writes share one
    SAVEPOINT: they describe the same visit, and neither is worth keeping
    without the other.

    Server-side renders are skipped (see ``_is_own_traffic``); the browser's own
    fetch for the same page is what gets recorded, and it carries the reader's
    IP and organisation.
    """
    if _is_own_traffic(request):
        return
    try:
        with db.begin_nested():
            AuthorAnalyticsService(db).log_view(
                model_id,
                viewer.organization_id if viewer else None,
                get_client_ip(request),
            )
            if viewer is not None:
                favorites_service.touch_recent(db, viewer.id, model_id)
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("Failed to record the visit to %s", model_id, exc_info=True)


@router.get("/catalog", response_model=ModelCatalogListResponse, operation_id="list_catalog_models")
def list_catalog_models(
    request: Request,
    viewer: OptionalCurrentUser,
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

    query = db.query(model_cls).filter(*MARKETPLACE_VISIBLE)

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

    # Impressions are keyed by model_project_id — the marketplace identity.
    _record_impressions(db, request, viewer, [i.id for i in items])

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
    viewer: OptionalCurrentUser,
    model_id: str,
    db: Session = Depends(get_db),
) -> ModelCatalogResponse:
    """Get details of a specific model in the catalog."""
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id, *MARKETPLACE_VISIBLE)
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

    _record_visit(db, request, viewer, model_id)

    return response


@router.get(
    "/catalog/{model_id}/schema",
    response_model=CatalogModelSchemaResponse,
    operation_id="get_catalog_model_schema",
)
def get_catalog_model_schema(
    model_id: str,
    db: Session = Depends(get_db),
) -> CatalogModelSchemaResponse:
    """Get the input schema and example for a catalog model.

    Requires ``is_public`` (like the detail endpoint): the schema exposes the
    generator + input fields, so a published-but-unlisted model must not leak it.
    """
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id, *MARKETPLACE_VISIBLE)
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Model not found")
    return CatalogModelSchemaResponse(
        id=listing.model_project_id,
        name=listing.name,
        generator_type=listing.generator_type,
        input_schema=listing.input_schema,
        input_fields=listing.input_fields,
        example_input=listing.example_input,
        scenario_description=listing.scenario_description,
    )
