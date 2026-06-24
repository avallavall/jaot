"""User public profile endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, ModelReview, Organization, User
from app.schemas.profile import (
    UpdateUserProfileRequest,
    UserPublicProfile,
    UserReviewResponse,
)
from app.shared.db.base import get_db

router = APIRouter(tags=["users"])


@router.get("/users/{user_id}/public", response_model=UserPublicProfile)
async def get_user_public_profile(
    user_id: str,
    db: Session = Depends(get_db),
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

    review_stats = (
        db.query(
            func.count(ModelReview.id).label("total"),
            func.avg(ModelReview.rating).label("avg_rating"),
        )
        .filter(ModelReview.user_id == user_id)
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
async def get_user_by_slug(
    slug: str,
    db: Session = Depends(get_db),
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

    return await get_user_public_profile(user.id, db)


@router.get("/users/{user_id}/reviews", response_model=list[UserReviewResponse])
async def get_user_reviews(
    user_id: str,
    db: Session = Depends(get_db),
) -> list[UserReviewResponse]:
    """Get all reviews written by a user."""
    reviews = (
        db.query(ModelReview)
        .filter(ModelReview.user_id == user_id)
        .order_by(ModelReview.created_at.desc())
        .limit(50)
        .all()
    )

    # Batch pre-fetch models to avoid N+1 queries
    model_ids = list({r.catalog_id for r in reviews if r.catalog_id})
    models_map = (
        {m.id: m for m in db.query(ModelCatalog).filter(ModelCatalog.id.in_(model_ids)).all()}
        if model_ids
        else {}
    )

    result = []
    for review in reviews:
        model = models_map.get(review.catalog_id)

        result.append(
            UserReviewResponse(
                id=review.id,
                catalog_id=review.catalog_id,
                model_name=model.display_name if model else "Unknown Model",
                rating=review.rating,
                title=review.title,
                comment=review.comment,
                created_at=review.created_at,
            )
        )

    return result


@router.patch("/users/profile")
async def update_user_profile(
    body: UpdateUserProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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

    return {"status": "updated"}
