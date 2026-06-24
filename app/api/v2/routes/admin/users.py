"""Admin user CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.schemas.admin import (
    AdminPaginatedResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.shared.db.base import get_db
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-users"])


@router.get("/users", response_model=AdminPaginatedResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    organization_id: str | None = None,
    search: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
) -> AdminPaginatedResponse:
    """List users with pagination and filters."""
    query = db.query(User)

    if organization_id:
        query = query.filter(User.organization_id == organization_id)
    if search:
        query = query.filter((User.name.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%")))
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    items, total = paginate_query(query, page, page_size)

    return AdminPaginatedResponse(
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: Session = Depends(get_db)) -> UserResponse:
    """Get user by ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """Create new user."""
    org = db.query(Organization).filter(Organization.id == data.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    role = "admin" if data.is_admin else "member"

    user = User(
        id=generate_id("usr_"),
        organization_id=data.organization_id,
        name=data.name,
        email=data.email,
        role=role,
        can_build_plugins=data.can_build_plugins,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str, data: UserUpdate, db: Session = Depends(get_db)
) -> UserResponse:
    """Update user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)

    # Handle is_admin -> role conversion
    if "is_admin" in update_data:
        update_data["role"] = "admin" if update_data.pop("is_admin") else "member"

    for key, value in update_data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, db: Session = Depends(get_db)) -> None:
    """Delete user (soft delete)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
