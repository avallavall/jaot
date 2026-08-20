"""Admin user CRUD endpoints."""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser, DBSession
from app.models import Organization, User
from app.schemas.admin import (
    AdminPaginatedResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.shared.core.http_errors import CodedHTTPException
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-users"])


@router.get("/users", response_model=AdminPaginatedResponse)
def list_users(
    db: DBSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    organization_id: str | None = None,
    search: str | None = None,
    is_active: bool | None = None,
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


def _refuse_locking_yourself_out(
    actor: User,
    target: User,
    *,
    new_role: str | None,
    new_is_active: bool | None,
) -> None:
    """Stop an administrator from taking away its own access.

    Pressing Edit on your own row and clearing the Admin tick answered 200, and
    the very next call answered 403 — the panel had just locked its own user
    out, and only another administrator or the database could undo it. Same for
    deactivating yourself.
    """
    if actor.id != target.id:
        return
    if new_role is not None and new_role != "admin":
        raise CodedHTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You cannot remove your own administrator access. Ask another "
                "administrator to do it."
            ),
            code="admin.cannot_demote_self",
        )
    if new_is_active is False:
        raise CodedHTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You cannot deactivate the account you are signed in with. Ask "
                "another administrator to do it."
            ),
            code="admin.cannot_deactivate_self",
        )


def _refuse_taken_email(db: DBSession, email: str | None, *, exclude_user_id: str | None) -> None:
    """Answer 409 when another account already has that address.

    The unique index made the commit raise, which reached the person as a 500
    saying "internal error". The address being taken is an ordinary thing to
    tell someone.
    """
    if not email:
        return
    query = db.query(User.id).filter(User.email == email)
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    if query.first():
        raise CodedHTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another account already uses that email address.",
            code="admin.email_taken",
            params={"email": email},
        )


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str, db: DBSession) -> UserResponse:
    """Get user by ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: DBSession) -> UserResponse:
    """Create new user."""
    org = db.query(Organization).filter(Organization.id == data.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    _refuse_taken_email(db, data.email, exclude_user_id=None)

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
def update_user(user_id: str, data: UserUpdate, db: DBSession, actor: AdminUser) -> UserResponse:
    """Update user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)

    # Handle is_admin -> role conversion
    if "is_admin" in update_data:
        update_data["role"] = "admin" if update_data.pop("is_admin") else "member"

    _refuse_locking_yourself_out(
        actor,
        user,
        new_role=update_data.get("role"),
        new_is_active=update_data.get("is_active"),
    )
    if "email" in update_data:
        _refuse_taken_email(db, update_data["email"], exclude_user_id=user.id)

    for key, value in update_data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, db: DBSession, actor: AdminUser) -> None:
    """Delete user (soft delete)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _refuse_locking_yourself_out(actor, user, new_role=None, new_is_active=False)
    user.is_active = False
    db.commit()
