"""Organization public profile endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, ModelReview, Organization, User
from app.schemas.model import ModelCatalogResponse
from app.schemas.profile import OrganizationPublicProfile, UpdateOrgProfileRequest
from app.shared.db.base import get_db

router = APIRouter(tags=["organizations"])


@router.get("/organizations/{org_id}/public", response_model=OrganizationPublicProfile)
async def get_organization_public_profile(
    org_id: str,
    db: Session = Depends(get_db),
) -> OrganizationPublicProfile:
    """Get public profile of an organization."""
    org = (
        db.query(Organization)
        .filter(
            Organization.id == org_id,
            Organization.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    models = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.author_organization_id == org_id,
            ModelCatalog.status == "published",
            ModelCatalog.is_public == True,  # noqa: E712
        )
        .all()
    )

    model_ids = [s.id for s in models]
    total_models = len(models)
    total_activations = sum(s.total_activations for s in models)
    total_executions = sum(s.total_executions for s in models)

    # Count reviews for this org's models
    total_reviews = 0
    if model_ids:
        total_reviews = (
            db.query(func.count(ModelReview.id))
            .filter(ModelReview.catalog_id.in_(model_ids))
            .scalar()
            or 0
        )

    avg_rating = None
    if models:
        ratings = [s.avg_rating for s in models if s.avg_rating is not None]
        if ratings:
            avg_rating = sum(ratings) / len(ratings)

    return OrganizationPublicProfile(
        id=org.id,
        name=org.name,
        slug=org.slug,
        bio=org.bio,
        logo_url=org.logo_url,
        website_url=org.website_url,
        linkedin_url=org.linkedin_url,
        twitter_url=org.twitter_url,
        is_verified=org.is_verified,
        created_at=org.created_at,
        total_models_published=total_models,
        total_activations=total_activations,
        total_executions=total_executions,
        total_reviews=total_reviews,
        avg_rating=avg_rating,
    )


@router.get("/organizations/by-slug/{slug}", response_model=OrganizationPublicProfile)
async def get_organization_by_slug(
    slug: str,
    db: Session = Depends(get_db),
) -> OrganizationPublicProfile:
    """Get public profile of an organization by slug."""
    org = (
        db.query(Organization)
        .filter(
            Organization.slug == slug,
            Organization.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    return await get_organization_public_profile(org.id, db)


@router.patch("/organizations/profile")
async def update_organization_profile(
    body: UpdateOrgProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update the current user's organization profile."""
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can update organization profile")

    if body.slug and body.slug != org.slug:
        existing = (
            db.query(Organization)
            .filter(
                Organization.slug == body.slug,
                Organization.id != org.id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Slug already taken")

    if body.slug is not None:
        org.slug = body.slug
    if body.bio is not None:
        org.bio = body.bio
    if body.logo_url is not None:
        org.logo_url = body.logo_url
    if body.website_url is not None:
        org.website_url = body.website_url
    if body.linkedin_url is not None:
        org.linkedin_url = body.linkedin_url
    if body.twitter_url is not None:
        org.twitter_url = body.twitter_url
    if body.is_public_profile is not None:
        org.is_public_profile = body.is_public_profile

    db.commit()

    return {"status": "updated"}


@router.get("/organizations/{org_id}/models", response_model=list[ModelCatalogResponse])
async def get_organization_models(
    org_id: str,
    db: Session = Depends(get_db),
) -> list[ModelCatalogResponse]:
    """Get public models published by an organization."""
    org = (
        db.query(Organization)
        .filter(
            Organization.id == org_id,
            Organization.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    models = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.author_organization_id == org_id,
            ModelCatalog.status == "published",
            ModelCatalog.is_public == True,  # noqa: E712
        )
        .order_by(ModelCatalog.total_executions.desc())
        .limit(50)
        .all()
    )

    items = []
    for s in models:
        item = ModelCatalogResponse.model_validate(s)
        item.author_name = org.name
        item.author_verified = org.is_verified
        items.append(item)
    return items
