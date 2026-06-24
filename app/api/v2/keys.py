"""API Key management endpoints for V2."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import APIKey, User
from app.schemas.api_key import (
    APIKeyInfo,
    CreateKeyRequest,
    CreateKeyResponse,
    KeyListResponse,
)
from app.services.auth import APIKeyService
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow

router = APIRouter(prefix="/keys", tags=["api-keys"])


@router.post("/", response_model=CreateKeyResponse)
async def create_api_key(
    request: CreateKeyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreateKeyResponse:
    """Create a new API key for the authenticated user."""
    expires_at = None
    if request.expires_days:
        expires_at = utcnow() + timedelta(days=request.expires_days)

    api_key_model, plaintext_key = APIKeyService.create_api_key(
        db=db,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        name=request.name,
        description=request.description,
        expires_at=expires_at,
    )
    db.commit()

    return CreateKeyResponse(
        api_key=plaintext_key,
        id=api_key_model.id,
        name=api_key_model.name or "",
        description=api_key_model.description,
        is_active=api_key_model.is_active,
        created_at=api_key_model.created_at.isoformat(),
    )


@router.get("/", response_model=KeyListResponse)
async def list_api_keys(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KeyListResponse:
    """List all API keys for the authenticated user."""
    # Limit max page size
    page_size = min(page_size, 100)

    query = db.query(APIKey).filter(APIKey.user_id == current_user.id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(APIKey.name.ilike(search_term), APIKey.key_prefix.ilike(search_term))
        )

    if is_active is not None:
        query = query.filter(APIKey.is_active == is_active)

    total = query.count()

    # Paginate
    query = query.order_by(APIKey.created_at.desc())
    keys = query.offset((page - 1) * page_size).limit(page_size).all()

    items = [
        APIKeyInfo(
            id=key.id,
            name=key.name or "Unnamed Key",
            key_prefix=key.key_prefix,
            description=key.description,
            is_active=key.is_active,
            created_at=key.created_at.isoformat() if key.created_at else "",
            last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
            expires_at=key.expires_at.isoformat() if key.expires_at else None,
        )
        for key in keys
    ]

    return KeyListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Revoke an API key."""
    # Verify key belongs to user
    key = (
        db.query(APIKey)
        .filter(
            APIKey.id == key_id,
            APIKey.user_id == current_user.id,
        )
        .first()
    )

    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    # Revoke key
    key.is_active = False
    db.commit()

    return {"message": "API key revoked successfully", "key_id": key_id}
