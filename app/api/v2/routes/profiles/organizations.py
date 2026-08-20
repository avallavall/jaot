"""Organization public profile endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func

from app.api.deps import DBSession
from app.api.v2.auth import get_current_user
from app.models import ModelProjectListing, ModelReview, Organization, User
from app.schemas.common import StatusResponse
from app.schemas.model import ModelCatalogResponse
from app.schemas.profile import OrganizationPublicProfile, UpdateOrgProfileRequest
from app.services.marketplace_fusion import MARKETPLACE_VISIBLE, listing_to_catalog_response

router = APIRouter(tags=["organizations"])


@router.get("/organizations/{org_id}/public", response_model=OrganizationPublicProfile)
def get_organization_public_profile(
    org_id: str,
    db: DBSession,
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
        db.query(ModelProjectListing)
        .filter(
            ModelProjectListing.author_organization_id == org_id,
            *MARKETPLACE_VISIBLE,
        )
        .all()
    )

    model_ids = [s.model_project_id for s in models]
    total_models = len(models)
    total_activations = sum(s.total_activations for s in models)
    total_executions = sum(s.total_executions for s in models)

    # Both numbers come off the same rows, in one pass.
    #
    # The average used to be the mean of each listing's own ``avg_rating``, so a
    # listing with one review weighed as much as one with fifty — a different
    # figure from "the average rating of this author's work" whenever the review
    # counts differ. And the count beside it did not filter ``is_visible``, so a
    # review hidden by moderation was still in the denominator the card prints
    # ("from N reviews") while being absent from the average above it.
    total_reviews = 0
    avg_rating = None
    if model_ids:
        count, average = (
            db.query(func.count(ModelReview.id), func.avg(ModelReview.rating))
            .filter(
                ModelReview.model_project_id.in_(model_ids),
                ModelReview.is_visible == True,  # noqa: E712
            )
            .one()
        )
        total_reviews = count or 0
        # ``func.avg`` returns Decimal on PostgreSQL; the schema wants a float.
        avg_rating = float(average) if average is not None else None

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
def get_organization_by_slug(
    slug: str,
    db: DBSession,
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

    return get_organization_public_profile(org.id, db)


@router.patch("/organizations/profile", response_model=StatusResponse)
def update_organization_profile(
    body: UpdateOrgProfileRequest,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> StatusResponse:
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

    return StatusResponse(status="updated")


@router.get("/organizations/{org_id}/models", response_model=list[ModelCatalogResponse])
def get_organization_models(
    org_id: str,
    db: DBSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> list[ModelCatalogResponse]:
    """Get public models published by an organization, fifty at a time.

    Paging is what makes the rest of them reachable. This used to take a fixed
    fifty and return them as the whole list, while the profile above reported
    the real total: the biggest author on the site published 102 models and 52
    of them could not be opened from their own page. The page count comes from
    ``total_models_published`` on the profile, which counts the same listings
    under the same filter.
    """
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
        db.query(ModelProjectListing)
        .filter(
            ModelProjectListing.author_organization_id == org_id,
            *MARKETPLACE_VISIBLE,
        )
        # Same tiebreaker the catalogue needs: execution counts tie constantly,
        # and without a total order WHICH fifty come back changes between
        # requests, so a model appears on an author page and is gone on reload.
        # With paging it matters twice over: an unstable order repeats a model
        # on page 2 and drops another one entirely.
        .order_by(
            ModelProjectListing.total_executions.desc(), ModelProjectListing.model_project_id.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for s in models:
        item = listing_to_catalog_response(s)
        item.author_name = org.name
        item.author_verified = org.is_verified
        items.append(item)
    return items
