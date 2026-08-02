"""User public profile endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func

from app.api.deps import DBSession
from app.api.v2.auth import get_current_user
from app.models import ModelProjectListing, ModelReview, Organization, User
from app.schemas.common import StatusResponse
from app.schemas.profile import (
    UpdateUserProfileRequest,
    UserPublicProfile,
    UserReviewResponse,
)
from app.services.marketplace_fusion import MARKETPLACE_VISIBLE

router = APIRouter(tags=["users"])


@router.get("/users/{user_id}/public", response_model=UserPublicProfile)
def get_user_public_profile(
    user_id: str,
    db: DBSession,
) -> UserPublicProfile:
    """Get public profile of a user."""
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    org = db.query(Organization).filter(Organization.id == user.organization_id).first()

    # Count the reviews this profile actually SHOWS. The list below drops any
    # review whose model has left the marketplace (its row is a link that would
    # 404), so counting every review the user ever wrote put "Reviews 12" above
    # a list of three the moment one model was withdrawn.
    review_stats = (
        db.query(
            func.count(ModelReview.id).label("total"),
            func.avg(ModelReview.rating).label("avg_rating"),
        )
        .join(
            ModelProjectListing,
            ModelProjectListing.model_project_id == ModelReview.model_project_id,
        )
        .filter(ModelReview.user_id == user_id, *MARKETPLACE_VISIBLE)
        .first()
    )

    return UserPublicProfile(
        id=user.id,
        name=user.name,
        display_name=user.display_name or user.name,
        slug=user.slug,
        bio=user.bio,
        avatar_url=user.avatar_url,
        linkedin_url=user.linkedin_url,
        twitter_url=user.twitter_url,
        organization_id=user.organization_id,
        organization_name=org.name if org else None,
        organization_verified=org.is_verified if org else False,
        created_at=user.created_at,
        total_reviews=review_stats.total or 0,
        avg_rating_given=float(review_stats.avg_rating) if review_stats.avg_rating else None,
    )


@router.get("/users/by-slug/{slug}", response_model=UserPublicProfile)
def get_user_by_slug(
    slug: str,
    db: DBSession,
) -> UserPublicProfile:
    """Get public profile of a user by slug."""
    user = (
        db.query(User)
        .filter(
            User.slug == slug,
            User.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return get_user_public_profile(user.id, db)


@router.get("/users/{user_id}/reviews", response_model=list[UserReviewResponse])
def get_user_reviews(
    user_id: str,
    db: DBSession,
) -> list[UserReviewResponse]:
    """Get all reviews written by a user."""
    reviews = (
        db.query(ModelReview)
        .filter(ModelReview.user_id == user_id)
        .order_by(ModelReview.created_at.desc())
        .limit(50)
        .all()
    )

    # Batch pre-fetch models (unified listing facet) to avoid N+1 queries. This is
    # a public profile and each row links to /marketplace/{catalog_id}, so it may
    # only carry models that page will actually serve.
    model_ids = list({r.model_project_id for r in reviews if r.model_project_id})
    models_map = (
        {
            m.model_project_id: m
            for m in db.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id.in_(model_ids), *MARKETPLACE_VISIBLE)
            .all()
        }
        if model_ids
        else {}
    )

    # A review whose model is no longer on the marketplace is dropped rather than
    # rendered as "Unknown Model": the row is a link, and naming it Unknown would
    # still offer the reader a page that 404s.
    return [
        UserReviewResponse(
            id=review.id,
            catalog_id=review.model_project_id,
            model_name=model.display_name,
            rating=review.rating,
            title=review.title,
            comment=review.comment,
            created_at=review.created_at,
        )
        for review in reviews
        if (model := models_map.get(review.model_project_id)) is not None
    ]


@router.patch("/users/profile", response_model=StatusResponse)
def update_user_profile(
    body: UpdateUserProfileRequest,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> StatusResponse:
    """Update the current user's profile."""
    user = db.query(User).filter(User.id == current_user.id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.slug and body.slug != user.slug:
        existing = (
            db.query(User)
            .filter(
                User.slug == body.slug,
                User.id != user.id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Slug already taken")

    if body.slug is not None:
        user.slug = body.slug
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.bio is not None:
        user.bio = body.bio
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url
    if body.linkedin_url is not None:
        user.linkedin_url = body.linkedin_url
    if body.twitter_url is not None:
        user.twitter_url = body.twitter_url
    if body.is_public_profile is not None:
        user.is_public_profile = body.is_public_profile
    if body.locale is not None:
        user.locale = body.locale

    db.commit()

    return StatusResponse(status="updated")
