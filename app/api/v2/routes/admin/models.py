"""Admin model management endpoints.

P1.5 fusion: the marketplace inventory an admin manages is the
``ModelProjectListing`` facet (id = the project id); "activated" means a fork
ModelProject seeded from-marketplace.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.models import APIKey, ModelProject, ModelProjectListing, Organization, User
from app.schemas.admin import AdminPaginatedResponse, UpdateModelBadgesRequest
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-models"])


@router.get("/stats")
def get_admin_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get admin dashboard statistics."""
    return {
        "organizations": {
            "total": db.query(Organization).count(),
            "active": db.query(Organization).filter(Organization.is_active == True).count(),  # noqa: E712
        },
        "users": {
            "total": db.query(User).count(),
            "active": db.query(User).filter(User.is_active == True).count(),  # noqa: E712
        },
        "api_keys": {
            "total": db.query(APIKey).count(),
            "active": db.query(APIKey).filter(APIKey.is_active == True).count(),  # noqa: E712
        },
        "models": {
            "catalog_total": db.query(ModelProjectListing).count(),
            "catalog_public": db.query(ModelProjectListing)
            .filter(ModelProjectListing.is_public == True)  # noqa: E712
            .count(),
            # "Activated" = fork ModelProjects seeded from a marketplace listing.
            "activated_total": db.query(ModelProject)
            .filter(ModelProject.source_type == "marketplace")
            .count(),
        },
    }


@router.get("/models", response_model=AdminPaginatedResponse)
def list_all_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    is_public: bool | None = None,
    db: Session = Depends(get_db),
) -> AdminPaginatedResponse:
    """List all marketplace listings (admin view)."""
    query = db.query(ModelProjectListing)

    if category:
        query = query.filter(ModelProjectListing.category == category)
    if is_public is not None:
        query = query.filter(ModelProjectListing.is_public == is_public)

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


@router.patch("/models/{model_id}/visibility")
def toggle_model_visibility(
    model_id: str,
    is_public: bool = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Toggle listing public visibility."""
    listing = _listing_or_404(db, model_id)

    listing.is_public = is_public
    db.commit()

    return {"success": True, "is_public": is_public}


@router.patch("/models/{model_id}")
def update_model_badges(
    model_id: str,
    body: UpdateModelBadgesRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update listing badges (official, featured, public)."""
    listing = _listing_or_404(db, model_id)

    if body.is_official is not None:
        listing.is_official = body.is_official
    if body.is_featured is not None:
        listing.is_featured = body.is_featured
    if body.is_public is not None:
        listing.is_public = body.is_public

    db.commit()

    return {
        "success": True,
        "id": listing.model_project_id,
        "is_official": listing.is_official,
        "is_featured": listing.is_featured,
        "is_public": listing.is_public,
    }
