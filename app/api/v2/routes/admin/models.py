"""Admin model management endpoints.

P1.5 fusion: the marketplace inventory an admin manages is the
``ModelProjectListing`` facet (id = the project id); "activated" means a fork
ModelProject seeded from-marketplace.
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import DBSession
from app.models import APIKey, ModelProjectListing, Organization, User
from app.schemas.admin import (
    AdminCountPair,
    AdminModelCounts,
    AdminPaginatedResponse,
    AdminStatsResponse,
    ModelBadgesResponse,
    ModelVisibilityResponse,
    UpdateModelBadgesRequest,
)
from app.services.author_analytics_service import adoption_query
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-models"])


@router.get("/stats", response_model=AdminStatsResponse)
def get_admin_stats(db: DBSession) -> AdminStatsResponse:
    """Get admin dashboard statistics."""
    return AdminStatsResponse(
        organizations=AdminCountPair(
            total=db.query(Organization).count(),
            active=db.query(Organization).filter(Organization.is_active == True).count(),  # noqa: E712
        ),
        users=AdminCountPair(
            total=db.query(User).count(),
            active=db.query(User).filter(User.is_active == True).count(),  # noqa: E712
        ),
        api_keys=AdminCountPair(
            total=db.query(APIKey).count(),
            active=db.query(APIKey).filter(APIKey.is_active == True).count(),  # noqa: E712
        ),
        models=AdminModelCounts(
            catalog_total=db.query(ModelProjectListing).count(),
            catalog_public=db.query(ModelProjectListing)
            .filter(ModelProjectListing.is_public == True)  # noqa: E712
            .count(),
            # The SAME adoption as the author-analytics page, from the same
            # query. This tile used to count every project tagged
            # `source_type="marketplace"`, with no join and no self-exclusion,
            # and show it under the word "adopted" beside a page that applied
            # both: 112 here against 2 there. 105 of that 112 carry
            # `source_ref = NULL` — projects that record no source at all.
            activated_total=adoption_query(db).count(),
        ),
    )


@router.get("/models", response_model=AdminPaginatedResponse)
def list_all_models(
    db: DBSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    is_public: bool | None = None,
    search: str | None = None,
) -> AdminPaginatedResponse:
    """List all marketplace listings (admin view)."""
    query = db.query(ModelProjectListing)

    if category:
        query = query.filter(ModelProjectListing.category == category)
    if is_public is not None:
        query = query.filter(ModelProjectListing.is_public == is_public)
    # `search` used to be dropped on the floor: FastAPI ignores a query
    # parameter no handler declares, so a caller who searched for a term that
    # matches nothing got the whole catalogue back and read it as 102 matches.
    # The admin users and organizations lists have always filtered on it.
    if search:
        term = f"%{search}%"
        query = query.filter(
            ModelProjectListing.name.ilike(term) | ModelProjectListing.display_name.ilike(term)
        )

    query = query.order_by(ModelProjectListing.created_at.desc())
    items, total = paginate_query(query, page, page_size)

    result_items = []
    for listing in items:
        result_items.append(
            {
                "id": listing.model_project_id,
                "name": listing.name,
                "display_name": listing.display_name,
                "description": listing.description,
                "category": listing.category,
                "version": listing.version,
                "is_public": listing.is_public,
                "is_official": listing.is_official,
                "is_featured": listing.is_featured,
                "created_at": listing.created_at.isoformat() if listing.created_at else None,
            }
        )

    return AdminPaginatedResponse(
        items=result_items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


def _listing_or_404(db: Session, model_id: str) -> ModelProjectListing:
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id)
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Model not found")
    return listing


@router.patch("/models/{model_id}/visibility", response_model=ModelVisibilityResponse)
def toggle_model_visibility(
    model_id: str,
    db: DBSession,
    is_public: bool = Query(...),
) -> ModelVisibilityResponse:
    """Toggle listing public visibility."""
    listing = _listing_or_404(db, model_id)

    listing.is_public = is_public
    db.commit()

    return ModelVisibilityResponse(success=True, is_public=is_public)


@router.patch("/models/{model_id}", response_model=ModelBadgesResponse)
def update_model_badges(
    model_id: str,
    body: UpdateModelBadgesRequest,
    db: DBSession,
) -> ModelBadgesResponse:
    """Update listing badges (official, featured, public)."""
    listing = _listing_or_404(db, model_id)

    if body.is_official is not None:
        listing.is_official = body.is_official
    if body.is_featured is not None:
        listing.is_featured = body.is_featured
    if body.is_public is not None:
        listing.is_public = body.is_public

    db.commit()

    return ModelBadgesResponse(
        success=True,
        id=listing.model_project_id,
        is_official=listing.is_official,
        is_featured=listing.is_featured,
        is_public=listing.is_public,
    )
