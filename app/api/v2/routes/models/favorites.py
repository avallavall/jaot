"""Favorites and recents endpoints for models."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, Organization, RecentModel, User, UserFavorite
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

    model_ids = [f.model_id for f in favorites]

    if not model_ids:
        return {"items": [], "total": 0}

    models = db.query(ModelCatalog).filter(ModelCatalog.id.in_(model_ids)).all()

    org_ids = list(set(s.author_organization_id for s in models if s.author_organization_id))
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    items = []
    for model in models:
        org = orgs.get(model.author_organization_id) if model.author_organization_id else None
        cat = model.category
        category_str = cat.value if hasattr(cat, "value") else (cat or "general")
        items.append(
            {
                "id": model.id,
                "name": model.name,
                "display_name": model.display_name,
                "description": model.description,
                "category": category_str,
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
    model = db.query(ModelCatalog).filter(ModelCatalog.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found in catalog")

    existing = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == current_user.id,
            UserFavorite.model_id == model_id,
        )
        .first()
    )

    if existing:
        return FavoriteResponse(model_id=model_id, is_favorite=True)

    favorite = UserFavorite(
        user_id=current_user.id,
        model_id=model_id,
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
            UserFavorite.model_id == model_id,
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
            UserFavorite.model_id == model_id,
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

    model_ids = [r.model_id for r in recents]

    if not model_ids:
        return {"items": [], "total": 0}

    models = {s.id: s for s in db.query(ModelCatalog).filter(ModelCatalog.id.in_(model_ids)).all()}

    org_ids = list(
        set(s.author_organization_id for s in models.values() if s.author_organization_id)
    )
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    items = []
    for recent in recents:
        model = models.get(str(recent.model_id))
        if model:
            org = orgs.get(model.author_organization_id) if model.author_organization_id else None
            cat = model.category
            category_str = cat.value if hasattr(cat, "value") else (cat or "general")
            items.append(
                {
                    "id": model.id,
                    "name": model.name,
                    "display_name": model.display_name,
                    "category": category_str,
                    "author_name": org.name if org else "Unknown",
                    "last_accessed": recent.last_accessed.isoformat(),
                    "access_count": recent.access_count,
                }
            )

    return {"items": items, "total": len(items)}
