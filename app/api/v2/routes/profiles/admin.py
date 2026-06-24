"""Admin profile management endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, ModelReview, Organization, User
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

router = APIRouter(prefix="/admin", tags=["admin-profiles"])


def _require_admin(user: User) -> None:
    """Check if user is admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.post("/organizations/{org_id}/verify")
async def verify_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Verify an organization (admin only)."""
    _require_admin(current_user)

    org = db.query(Organization).filter(Organization.id == org_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.is_verified = True
    db.commit()

    return {"status": "verified", "organization_id": org_id}


@router.delete("/organizations/{org_id}/verify")
async def unverify_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove verification from an organization (admin only)."""
    _require_admin(current_user)

    org = db.query(Organization).filter(Organization.id == org_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.is_verified = False
    db.commit()

    return {"status": "unverified", "organization_id": org_id}


@router.get("/reviews/reported")
async def get_reported_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get reported reviews for moderation (admin only)."""
    _require_admin(current_user)

    query = (
        db.query(ModelReview)
        .filter(
            ModelReview.is_reported == True,  # noqa: E712
        )
        .order_by(ModelReview.created_at.desc())
    )

    reviews, total = paginate_query(query, page, page_size)

    # Batch pre-fetch users and models to avoid N+1 queries
    user_ids = list({r.user_id for r in reviews if r.user_id})
    model_ids = list({r.catalog_id for r in reviews if r.catalog_id})
    users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    )
    models_map = (
        {m.id: m for m in db.query(ModelCatalog).filter(ModelCatalog.id.in_(model_ids)).all()}
        if model_ids
        else {}
    )

    items = []
    for r in reviews:
        user = users.get(r.user_id)
        model = models_map.get(r.catalog_id)

        items.append(
            {
                "id": r.id,
                "catalog_id": r.catalog_id,
                "model_name": model.display_name if model else None,
                "user_id": r.user_id,
                "user_name": user.name if user else None,
                "rating": r.rating,
                "title": r.title,
                "comment": r.comment,
                "report_reason": r.report_reason,
                "created_at": r.created_at,
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.delete("/reviews/{review_id}")
async def admin_delete_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a review (admin only)."""
    _require_admin(current_user)

    review = db.query(ModelReview).filter(ModelReview.id == review_id).first()

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


@router.patch("/reviews/{review_id}/visibility")
async def toggle_review_visibility(
    review_id: str,
    visible: bool = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Toggle review visibility (admin only)."""
    _require_admin(current_user)

    review = db.query(ModelReview).filter(ModelReview.id == review_id).first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_visible = visible
    review.is_reported = False  # Clear report flag
    db.commit()

    return {"status": "updated", "is_visible": visible}
