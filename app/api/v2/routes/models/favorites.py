"""Favorites and recents endpoints for models.

P1.5 fusion: favorites/recents are keyed on the unified Model (``model_project_id``) and
read from the ``ModelProjectListing`` facet. The public route paths keep ``{model_id}``
for URL stability; the id they carry is the model-project id.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelProjectListing, Organization, RecentModel, User, UserFavorite
from app.schemas.model import FavoriteResponse
from app.shared.db.base import get_db

router = APIRouter(tags=["favorites"])


@router.get("/favorites")
async def get_user_favorites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get user's favorite models."""
    favorites = db.query(UserFavorite).filter(UserFavorite.user_id == current_user.id).all()

    model_ids = [f.model_project_id for f in favorites if f.model_project_id]

    if not model_ids:
        return {"items": [], "total": 0}

    models = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id.in_(model_ids))
        .all()
    )

    org_ids = list({s.author_organization_id for s in models if s.author_organization_id})
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    items = []
    for model in models:
        org = orgs.get(model.author_organization_id) if model.author_organization_id else None
        items.append(
            {
                "id": model.model_project_id,
                "name": model.name,
                "display_name": model.display_name,
                "description": model.description,
                "category": model.category or "general",
                "author_name": org.name if org else "Unknown",
                "is_official": model.is_official,
                "is_featured": model.is_featured,
                "avg_rating": model.avg_rating,
            }
        )

    return {"items": items, "total": len(items)}


@router.post("/favorites/{model_id}")
async def add_favorite(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FavoriteResponse:
    """Add a model to favorites."""
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id)
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Model not found in catalog")

    existing = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == current_user.id,
            UserFavorite.model_project_id == model_id,
        )
        .first()
    )

    if existing:
        return FavoriteResponse(model_id=model_id, is_favorite=True)

    favorite = UserFavorite(
        user_id=current_user.id,
        model_project_id=model_id,
    )
    db.add(favorite)
    db.commit()

    return FavoriteResponse(model_id=model_id, is_favorite=True)


@router.delete("/favorites/{model_id}")
async def remove_favorite(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FavoriteResponse:
    """Remove a model from favorites."""
    favorite = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == current_user.id,
            UserFavorite.model_project_id == model_id,
        )
        .first()
    )

    if favorite:
        db.delete(favorite)
        db.commit()

    return FavoriteResponse(model_id=model_id, is_favorite=False)


@router.get("/favorites/{model_id}/status")
async def get_favorite_status(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FavoriteResponse:
    """Check if a model is favorited by the current user."""
    favorite = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == current_user.id,
            UserFavorite.model_project_id == model_id,
        )
        .first()
    )

    return FavoriteResponse(model_id=model_id, is_favorite=favorite is not None)


@router.get("/recents")
async def get_recent_models(
    current_user: User = Depends(get_current_user),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get user's recently accessed models."""
    recents = (
        db.query(RecentModel)
        .filter(RecentModel.user_id == current_user.id)
        .order_by(RecentModel.last_accessed.desc())
        .limit(limit)
        .all()
    )

    model_ids = [r.model_project_id for r in recents if r.model_project_id]

    if not model_ids:
        return {"items": [], "total": 0}

    models = {
        s.model_project_id: s
        for s in db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id.in_(model_ids))
        .all()
    }

    org_ids = list({s.author_organization_id for s in models.values() if s.author_organization_id})
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    items = []
    for recent in recents:
        model = models.get(recent.model_project_id)
        if model:
            org = orgs.get(model.author_organization_id) if model.author_organization_id else None
            items.append(
                {
                    "id": model.model_project_id,
                    "name": model.name,
                    "display_name": model.display_name,
                    "category": model.category or "general",
                    "author_name": org.name if org else "Unknown",
                    "last_accessed": recent.last_accessed.isoformat(),
                    "access_count": recent.access_count,
                }
            )

    return {"items": items, "total": len(items)}
