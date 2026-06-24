"""Admin organization CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import APIKey, Organization, OrganizationModel, User
from app.schemas.admin import (
    AdminPaginatedResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.shared.db.base import get_db
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-organizations"])


@router.get("/organizations", response_model=AdminPaginatedResponse)
async def list_organizations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    plan: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
) -> AdminPaginatedResponse:
    """List all organizations with pagination and filters."""
    query = db.query(Organization)

    if search:
        query = query.filter(Organization.name.ilike(f"%{search}%"))
    if plan:
        query = query.filter(Organization.plan == plan)
    if is_active is not None:
        query = query.filter(Organization.is_active == is_active)

    items, total = paginate_query(query, page, page_size)

    # Batch COUNT queries to avoid N+1 (3 queries instead of N*3)
    org_ids = [org.id for org in items]

    user_counts = (
        dict(
            db.query(User.organization_id, func.count(User.id))
            .filter(User.organization_id.in_(org_ids))
            .group_by(User.organization_id)
            .all()
        )
        if org_ids
        else {}
    )

    key_counts = (
        dict(
            db.query(APIKey.organization_id, func.count(APIKey.id))
            .filter(APIKey.organization_id.in_(org_ids))
            .group_by(APIKey.organization_id)
            .all()
        )
        if org_ids
        else {}
    )

    model_counts = (
        dict(
            db.query(OrganizationModel.organization_id, func.count(OrganizationModel.id))
            .filter(OrganizationModel.organization_id.in_(org_ids))
            .group_by(OrganizationModel.organization_id)
            .all()
        )
        if org_ids
        else {}
    )

    result_items = []
    for org in items:
        org_dict = OrganizationResponse.model_validate(org).model_dump()
        org_dict["user_count"] = user_counts.get(org.id, 0)
        org_dict["api_key_count"] = key_counts.get(org.id, 0)
        org_dict["model_count"] = model_counts.get(org.id, 0)
        result_items.append(org_dict)

    return AdminPaginatedResponse(
        items=result_items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/organizations/{org_id}", response_model=OrganizationResponse)
async def get_organization(org_id: str, db: Session = Depends(get_db)) -> OrganizationResponse:
    """Get organization by ID."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    response = OrganizationResponse.model_validate(org)
    response.user_count = db.query(User).filter(User.organization_id == org.id).count()
    response.api_key_count = db.query(APIKey).filter(APIKey.organization_id == org.id).count()
    response.model_count = (
        db.query(OrganizationModel).filter(OrganizationModel.organization_id == org.id).count()
    )

    return response


@router.post(
    "/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED
)
async def create_organization(
    data: OrganizationCreate, db: Session = Depends(get_db)
) -> OrganizationResponse:
    """Create new organization."""
    org = Organization(
        id=generate_id("org_"),
        name=data.name,
        plan=data.plan,
        credits_balance=data.credits_balance,
        monthly_quota=data.monthly_quota,
        rate_limit_per_minute=data.rate_limit_per_minute,
        rate_limit_per_day=data.rate_limit_per_day,
        ai_builder_enabled=data.ai_builder_enabled,
        max_private_plugins=data.max_private_plugins,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return OrganizationResponse.model_validate(org)


@router.patch("/organizations/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str, data: OrganizationUpdate, db: Session = Depends(get_db)
) -> OrganizationResponse:
    """Update organization."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(org, key, value)

    db.commit()
    db.refresh(org)
    return OrganizationResponse.model_validate(org)


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(org_id: str, db: Session = Depends(get_db)) -> None:
    """Delete organization (soft delete by setting is_active=False)."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.is_active = False
    db.commit()
