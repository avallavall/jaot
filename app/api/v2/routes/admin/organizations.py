"""Admin organization CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    APIKey,
    CreditTransaction,
    ModelExecution,
    Organization,
    OrganizationModel,
    User,
)
from app.schemas.admin import (
    AdminPaginatedResponse,
    APIKeyResponse,
    OrganizationCreate,
    OrganizationOverviewResponse,
    OrganizationResponse,
    OrganizationUpdate,
    OrgCounts,
    OrgDetail,
    OrgExecutionStats,
    OrgExecutionSummary,
    OrgModelSummary,
    OrgOwnerSummary,
    OrgTransactionSummary,
    UserResponse,
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


@router.get("/organizations/{org_id}/overview", response_model=OrganizationOverviewResponse)
async def get_organization_overview(
    org_id: str, db: Session = Depends(get_db)
) -> OrganizationOverviewResponse:
    """Rich read-only overview of one organization for platform admins.

    Aggregates everything an admin needs to "see" an org without editing it:
    members, API keys, models, recent solve executions, credit movements, and
    usage/limit configuration. Read-only — no row is mutated here.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    users = db.query(User).filter(User.organization_id == org_id).order_by(User.created_at).all()
    api_keys = (
        db.query(APIKey)
        .filter(APIKey.organization_id == org_id)
        .order_by(APIKey.created_at.desc())
        .all()
    )
    org_models = (
        db.query(OrganizationModel)
        .filter(OrganizationModel.organization_id == org_id)
        .order_by(OrganizationModel.created_at.desc())
        .all()
    )

    execution_count = (
        db.query(ModelExecution).filter(ModelExecution.organization_id == org_id).count()
    )
    status_rows = (
        db.query(ModelExecution.status, func.count(ModelExecution.id))
        .filter(ModelExecution.organization_id == org_id)
        .group_by(ModelExecution.status)
        .all()
    )
    status_counts = dict(status_rows)
    credits_consumed_total = (
        db.query(func.coalesce(func.sum(ModelExecution.credits_consumed), 0))
        .filter(ModelExecution.organization_id == org_id)
        .scalar()
        or 0
    )

    # organization_model (and its catalog_model) are relationship(lazy="joined"),
    # so reading e.organization_model.display_name below is eager — no N+1.
    recent_executions = (
        db.query(ModelExecution)
        .filter(ModelExecution.organization_id == org_id)
        .order_by(ModelExecution.created_at.desc())
        .limit(20)
        .all()
    )
    recent_transactions = (
        db.query(CreditTransaction)
        .filter(CreditTransaction.organization_id == org_id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(20)
        .all()
    )

    owner: OrgOwnerSummary | None = None
    if org.owner_user_id:
        owner_user = db.query(User).filter(User.id == org.owner_user_id).first()
        if owner_user:
            owner = OrgOwnerSummary(id=owner_user.id, name=owner_user.name, email=owner_user.email)

    detail = OrgDetail.model_validate(org)
    detail.byok_configured = bool(org.anthropic_api_key_encrypted)

    counts = OrgCounts(
        users=len(users),
        active_users=sum(1 for u in users if u.is_active),
        api_keys=len(api_keys),
        active_api_keys=sum(1 for k in api_keys if k.is_active),
        models=len(org_models),
        executions=execution_count,
    )

    execution_stats = OrgExecutionStats(
        total=execution_count,
        completed=status_counts.get("completed", 0),
        failed=status_counts.get("failed", 0)
        + status_counts.get("timeout", 0)
        + status_counts.get("cancelled", 0),
        running=status_counts.get("running", 0) + status_counts.get("pending", 0),
        credits_consumed_total=int(credits_consumed_total),
    )

    return OrganizationOverviewResponse(
        organization=detail,
        owner=owner,
        counts=counts,
        execution_stats=execution_stats,
        users=[UserResponse.model_validate(u) for u in users],
        api_keys=[APIKeyResponse.model_validate(k) for k in api_keys],
        models=[
            OrgModelSummary(
                id=m.id,
                display_name=m.display_name,
                catalog_id=m.catalog_id,
                source="marketplace" if m.catalog_id else "custom",
                is_active=m.is_active,
                total_executions=m.total_executions,
                total_credits_used=m.total_credits_used,
                last_executed_at=m.last_executed_at,
                created_at=m.created_at,
            )
            for m in org_models
        ],
        recent_executions=[
            OrgExecutionSummary(
                id=e.id,
                status=e.status,
                solver_name=e.solver_name,
                credits_consumed=e.credits_consumed,
                execution_time_ms=e.execution_time_ms,
                objective_value=e.objective_value,
                model_display_name=(
                    e.organization_model.display_name if e.organization_model else None
                ),
                executed_by_user_id=e.executed_by_user_id,
                created_at=e.created_at,
            )
            for e in recent_executions
        ],
        recent_transactions=[
            OrgTransactionSummary(
                id=t.id,
                transaction_type=t.transaction_type,
                credits_amount=t.credits_amount,
                balance_after=t.balance_after,
                description=t.description,
                created_at=t.created_at,
            )
            for t in recent_transactions
        ],
    )


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
