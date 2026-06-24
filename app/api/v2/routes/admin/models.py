"""Admin model management endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import APIKey, ModelCatalog, Organization, OrganizationModel, User
from app.schemas.admin import AdminPaginatedResponse, UpdateModelBadgesRequest
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-models"])


@router.get("/stats")
async def get_admin_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
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
            "catalog_total": db.query(ModelCatalog).count(),
            "catalog_public": db.query(ModelCatalog).filter(ModelCatalog.is_public == True).count(),  # noqa: E712
            "activated_total": db.query(OrganizationModel).count(),
        },
        "credits": {
            "total_balance": db.query(func.sum(Organization.credits_balance)).scalar() or 0,
        },
    }


@router.get("/models", response_model=AdminPaginatedResponse)
async def list_all_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    is_public: bool | None = None,
    db: Session = Depends(get_db),
) -> AdminPaginatedResponse:
    """List all models in the catalog (admin view)."""
    query = db.query(ModelCatalog)

    if category:
        query = query.filter(ModelCatalog.category == category)
    if is_public is not None:
        query = query.filter(ModelCatalog.is_public == is_public)

    query = query.order_by(ModelCatalog.created_at.desc())
    items, total = paginate_query(query, page, page_size)

    result_items = []
    for model in items:
        result_items.append(
            {
                "id": model.id,
                "name": model.name,
                "display_name": model.display_name,
                "description": model.description,
                "category": model.category,
                "version": model.version,
                "is_public": model.is_public,
                "is_official": model.is_official,
                "is_featured": model.is_featured,
                "credits_per_execution": model.credits_per_execution,
                "created_at": model.created_at.isoformat() if model.created_at else None,
            }
        )

    return AdminPaginatedResponse(
        items=result_items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.patch("/models/{model_id}/visibility")
async def toggle_model_visibility(
    model_id: str,
    is_public: bool = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Toggle model public visibility."""
    model = db.query(ModelCatalog).filter(ModelCatalog.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    model.is_public = is_public
    db.commit()

    return {"success": True, "is_public": is_public}


@router.patch("/models/{model_id}")
async def update_model_badges(
    model_id: str,
    body: UpdateModelBadgesRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update model badges (official, featured, public)."""
    model = db.query(ModelCatalog).filter(ModelCatalog.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if body.is_official is not None:
        model.is_official = body.is_official
    if body.is_featured is not None:
        model.is_featured = body.is_featured
    if body.is_public is not None:
        model.is_public = body.is_public

    db.commit()

    return {
        "success": True,
        "id": model.id,
        "is_official": model.is_official,
        "is_featured": model.is_featured,
        "is_public": model.is_public,
    }
