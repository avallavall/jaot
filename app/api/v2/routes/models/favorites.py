"""Favorites and recents endpoints for models.

P1.5 fusion: favorites/recents are keyed on the unified Model (``model_project_id``) and
read from the ``ModelProjectListing`` facet. The public route paths keep ``{model_id}``
for URL stability; the id they carry is the model-project id.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import (
    ModelProject,
    ModelProjectListing,
    Organization,
    RecentModel,
    User,
    UserFavorite,
)
from app.schemas.model import FavoriteResponse
from app.shared.db.base import get_db

router = APIRouter(tags=["favorites"])


def _author_names(db: Session, listings: list[ModelProjectListing]) -> dict[str, str]:
    """Resolve each listing's author-org display name, keyed by model_project_id.

    Backfilled/legacy listings may lack ``author_organization_id`` (the legacy
    catalog never carried it) — fall back to the owning project's organization,
    which in the fused model IS the publisher.
    """
    project_orgs: dict[str, str] = {}
    missing = [s.model_project_id for s in listings if not s.author_organization_id]
    if missing:
        rows = (
            db.query(ModelProject.id, ModelProject.organization_id)
            .filter(ModelProject.id.in_(missing))
            .all()
        )
        project_orgs = {pid: oid for pid, oid in rows if oid}

    org_ids = {s.author_organization_id for s in listings if s.author_organization_id}
    org_ids.update(project_orgs.values())
    orgs = (
        {o.id: o.name for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    names: dict[str, str] = {}
    for s in listings:
        org_id = s.author_organization_id or project_orgs.get(s.model_project_id)
        names[s.model_project_id] = orgs.get(org_id, "Unknown") if org_id else "Unknown"
    return names


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

    authors = _author_names(db, models)

    items = []
    for model in models:
        items.append(
            {
                "id": model.model_project_id,
                "name": model.name,
                "display_name": model.display_name,
                "description": model.description,
                "category": model.category or "general",
                "author_name": authors[model.model_project_id],
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

    authors = _author_names(db, list(models.values()))

    items = []
    for recent in recents:
        model = models.get(recent.model_project_id)
        if model:
            items.append(
                {
                    "id": model.model_project_id,
                    "name": model.name,
                    "display_name": model.display_name,
                    "category": model.category or "general",
                    "author_name": authors[model.model_project_id],
                    "last_accessed": recent.last_accessed.isoformat(),
                    "access_count": recent.access_count,
                }
            )

    return {"items": items, "total": len(items)}
