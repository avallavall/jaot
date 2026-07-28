"""Favorites and recents endpoints for models.

P1.5 fusion: favorites/recents are keyed on the unified Model (``model_project_id``) and
read from the ``ModelProjectListing`` facet. The public route paths keep ``{model_id}``
for URL stability; the id they carry is the model-project id.
"""

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DBSession
from app.schemas.model import FavoriteListResponse, FavoriteResponse, RecentListResponse
from app.services import favorites_service

router = APIRouter(tags=["favorites"])


@router.get("/favorites", response_model=FavoriteListResponse)
def get_user_favorites(current_user: CurrentUser, db: DBSession) -> FavoriteListResponse:
    """Get user's favorite models."""
    return favorites_service.list_favorites(db, current_user.id)


@router.post("/favorites/{model_id}", response_model=FavoriteResponse)
def add_favorite(model_id: str, current_user: CurrentUser, db: DBSession) -> FavoriteResponse:
    """Add a model to favorites."""
    if not favorites_service.listing_exists(db, model_id):
        raise HTTPException(status_code=404, detail="Model not found in catalog")

    favorites_service.add_favorite(db, current_user.id, model_id)
    return FavoriteResponse(model_id=model_id, is_favorite=True)


@router.delete("/favorites/{model_id}", response_model=FavoriteResponse)
def remove_favorite(model_id: str, current_user: CurrentUser, db: DBSession) -> FavoriteResponse:
    """Remove a model from favorites."""
    favorites_service.remove_favorite(db, current_user.id, model_id)
    return FavoriteResponse(model_id=model_id, is_favorite=False)


@router.get("/favorites/{model_id}/status", response_model=FavoriteResponse)
def get_favorite_status(
    model_id: str, current_user: CurrentUser, db: DBSession
) -> FavoriteResponse:
    """Check if a model is favorited by the current user."""
    favorite = favorites_service.find_favorite(db, current_user.id, model_id)
    return FavoriteResponse(model_id=model_id, is_favorite=favorite is not None)


@router.get("/recents", response_model=RecentListResponse)
def get_recent_models(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = Query(10, ge=1, le=50),
) -> RecentListResponse:
    """Get user's recently accessed models."""
    return favorites_service.list_recents(db, current_user.id, limit)
