"""Model review endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import (
    ModelCatalog,
    ModelExecution,
    ModelReview,
    Organization,
    OrganizationModel,
    User,
)
from app.schemas.profile import (
    CreateReviewRequest,
    ReportRequest,
    ReviewListResponse,
    ReviewResponse,
)
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["reviews"])


@router.get("/models/catalog/{catalog_id}/reviews", response_model=ReviewListResponse)
async def get_model_reviews(
    catalog_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    """Get reviews for a model."""
    model = db.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    query = (
        db.query(ModelReview)
        .filter(
            ModelReview.catalog_id == catalog_id,
            ModelReview.is_visible == True,  # noqa: E712
        )
        .order_by(ModelReview.created_at.desc())
    )

    reviews, total = paginate_query(query, page, page_size)

    # Batch pre-fetch users and organizations to avoid N+1 queries
    user_ids = list({r.user_id for r in reviews if r.user_id})
    org_ids = list({r.organization_id for r in reviews if r.organization_id})
    users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    )
    orgs = (
        {o.id: o for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    items = []
    for r in reviews:
        user = users.get(r.user_id)
        org = orgs.get(r.organization_id)

        items.append(
            ReviewResponse(
                id=r.id,
                catalog_id=r.catalog_id,
                user_id=r.user_id,
                user_name=user.display_name or user.name if user else "Anonymous",
                user_avatar_url=user.avatar_url if user else None,
                organization_name=org.name if org else None,
                rating=r.rating,
                title=r.title,
                comment=r.comment,
                created_at=r.created_at,
            )
        )

    # Calculate rating distribution with a single GROUP BY query (avoids full table scan)
    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    rating_counts = (
        db.query(ModelReview.rating, func.count(ModelReview.rating))
        .filter(
            ModelReview.catalog_id == catalog_id,
            ModelReview.is_visible == True,  # noqa: E712
        )
        .group_by(ModelReview.rating)
        .all()
    )
    for rating, count in rating_counts:
        distribution[rating] = count

    return ReviewListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        avg_rating=model.avg_rating,
        rating_distribution=distribution,
    )


@router.post("/models/catalog/{catalog_id}/reviews", response_model=ReviewResponse)
async def create_review(
    catalog_id: str,
    body: CreateReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewResponse:
    """Create a review for a model. User must have executed the model."""
    model = db.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    existing = (
        db.query(ModelReview)
        .filter(
            ModelReview.catalog_id == catalog_id,
            ModelReview.user_id == current_user.id,
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="You have already reviewed this model")

    org_model = (
        db.query(OrganizationModel)
        .filter(
            OrganizationModel.catalog_id == catalog_id,
            OrganizationModel.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not org_model:
        raise HTTPException(
            status_code=403, detail="You must activate and use this model before reviewing"
        )

    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.organization_model_id == org_model.id,
            ModelExecution.status == "completed",
        )
        .first()
    )

    if not execution:
        raise HTTPException(
            status_code=403, detail="You must successfully execute this model before reviewing"
        )

    review = ModelReview(
        id=str(uuid.uuid4()),
        catalog_id=catalog_id,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        rating=body.rating,
        title=body.title,
        comment=body.comment,
    )

    db.add(review)

    all_ratings = (
        db.query(ModelReview.rating)
        .filter(
            ModelReview.catalog_id == catalog_id,
            ModelReview.is_visible == True,  # noqa: E712
        )
        .all()
    )

    ratings = [r[0] for r in all_ratings] + [body.rating]
    model.avg_rating = sum(ratings) / len(ratings)

    db.commit()
    db.refresh(review)

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

    return ReviewResponse(
        id=review.id,
        catalog_id=review.catalog_id,
        user_id=review.user_id,
        user_name=current_user.display_name or current_user.name,
        user_avatar_url=current_user.avatar_url,
        organization_name=org.name if org else None,
        rating=review.rating,
        title=review.title,
        comment=review.comment,
        created_at=review.created_at,
    )


@router.delete("/models/reviews/{review_id}")
async def delete_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete own review."""
    review = (
        db.query(ModelReview)
        .filter(
            ModelReview.id == review_id,
            ModelReview.user_id == current_user.id,
        )
        .first()
    )

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    catalog_id = review.catalog_id
    db.delete(review)

    # Recalculate avg_rating
    model = db.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()

    if model:
        all_ratings = (
            db.query(ModelReview.rating)
            .filter(
                ModelReview.catalog_id == catalog_id,
                ModelReview.is_visible == True,  # noqa: E712
            )
            .all()
        )

        if all_ratings:
            model.avg_rating = sum(r[0] for r in all_ratings) / len(all_ratings)
        else:
            model.avg_rating = None

    db.commit()

    return {"status": "deleted"}


@router.post("/models/reviews/{review_id}/report")
async def report_review(
    review_id: str,
    body: ReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Report a review as inappropriate."""
    review = (
        db.query(ModelReview)
        .filter(
            ModelReview.id == review_id,
        )
        .first()
    )

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_reported = True
    review.report_reason = body.reason
    db.commit()

    return {"status": "reported"}
