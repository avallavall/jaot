"""Admin API key management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models import APIKey, Organization, User
from app.schemas.admin import (
    AdminPaginatedResponse,
    APIKeyCreate,
    APIKeyResponse,
)
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-api-keys"])


@router.get("/api-keys", response_model=AdminPaginatedResponse)
async def list_api_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    organization_id: str | None = None,
    user_id: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
) -> AdminPaginatedResponse:
    """List API keys with pagination and filters."""
    query = db.query(APIKey)

    if organization_id:
        query = query.filter(APIKey.organization_id == organization_id)
    if user_id:
        query = query.filter(APIKey.user_id == user_id)
    if is_active is not None:
        query = query.filter(APIKey.is_active == is_active)

    items, total = paginate_query(query, page, page_size)

    return AdminPaginatedResponse(
        items=[APIKeyResponse.model_validate(k) for k in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/api-keys", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(data: APIKeyCreate, db: Session = Depends(get_db)) -> APIKeyResponse:
    """Create new API key. Returns full key only once."""
    from app.services.auth import APIKeyService

    org = db.query(Organization).filter(Organization.id == data.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    api_key, full_key = APIKeyService.create_api_key(
        db=db,
        user_id=data.user_id,
        organization_id=data.organization_id,
        name=data.name,
        description=data.description,
    )

    response = APIKeyResponse.model_validate(api_key)
    response.full_key = full_key
    return response


@router.patch("/api-keys/{key_id}/toggle", response_model=APIKeyResponse)
async def toggle_api_key(key_id: str, db: Session = Depends(get_db)) -> APIKeyResponse:
    """Toggle API key active status."""
    key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = not key.is_active
    db.commit()
    db.refresh(key)
    return APIKeyResponse.model_validate(key)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(key_id: str, db: Session = Depends(get_db)) -> None:
    """Delete API key (hard delete)."""
    key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    db.delete(key)
    db.commit()
