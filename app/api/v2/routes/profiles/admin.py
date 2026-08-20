"""Admin profile management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import DBSession
from app.api.v2.auth import get_current_user
from app.models import (
    ModelProjectListing,
    ModelReview,
    ModelReviewReport,
    Organization,
    User,
)
from app.schemas.common import StatusResponse
from app.schemas.profile import (
    OrganizationVerificationResponse,
    ReportedReviewListResponse,
    ReportedReviewResponse,
    ReviewReportResponse,
    ReviewVisibilityResponse,
)
from app.shared.utils.pagination import paginate_query

router = APIRouter(prefix="/admin", tags=["admin-profiles"])


def _require_admin(user: User) -> None:
    """Check if user is admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.post("/organizations/{org_id}/verify", response_model=OrganizationVerificationResponse)
def verify_organization(
    org_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> OrganizationVerificationResponse:
    """Verify an organization (admin only)."""
    _require_admin(current_user)

    org = db.query(Organization).filter(Organization.id == org_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.is_verified = True
    db.commit()

    return OrganizationVerificationResponse(status="verified", organization_id=org_id)


@router.delete("/organizations/{org_id}/verify", response_model=OrganizationVerificationResponse)
def unverify_organization(
    org_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> OrganizationVerificationResponse:
    """Remove verification from an organization (admin only)."""
    _require_admin(current_user)

    org = db.query(Organization).filter(Organization.id == org_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.is_verified = False
    db.commit()

    return OrganizationVerificationResponse(status="unverified", organization_id=org_id)


@router.get("/reviews/reported", response_model=ReportedReviewListResponse)
def get_reported_reviews(
    db: DBSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> ReportedReviewListResponse:
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

    # Batch pre-fetch users and models (unified listing facet) to avoid N+1 queries
    user_ids = list({r.user_id for r in reviews if r.user_id})
    model_ids = list({r.model_project_id for r in reviews if r.model_project_id})
    users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    )
    models_map = (
        {
            m.model_project_id: m
            for m in db.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id.in_(model_ids))
            .all()
        }
        if model_ids
        else {}
    )

    # Who reported each one, in one query for the page. Asking per row would be
    # a round trip per review, and this list is what a moderator reads first.
    review_ids = [r.id for r in reviews]
    reports_by_review: dict[str, list[ModelReviewReport]] = {}
    # Hoisted: the comprehension below reads it whatever the page holds.
    reporters: dict[str, User] = {}
    if review_ids:
        rows = (
            db.query(ModelReviewReport)
            .filter(ModelReviewReport.review_id.in_(review_ids))
            .order_by(ModelReviewReport.created_at.desc())
            .all()
        )
        reporter_ids = list({row.user_id for row in rows})
        if reporter_ids:
            reporters = {u.id: u for u in db.query(User).filter(User.id.in_(reporter_ids)).all()}
        for row in rows:
            reports_by_review.setdefault(row.review_id, []).append(row)

    items = []
    for r in reviews:
        user = users.get(r.user_id)
        model = models_map.get(r.model_project_id)

        items.append(
            ReportedReviewResponse(
                id=r.id,
                catalog_id=r.model_project_id,
                model_name=model.display_name if model else None,
                user_id=r.user_id,
                user_name=user.name if user else None,
                rating=r.rating,
                title=r.title,
                comment=r.comment,
                report_reason=r.report_reason,
                report_count=len(reports_by_review.get(r.id, [])),
                reports=[
                    ReviewReportResponse(
                        user_id=row.user_id,
                        user_name=(
                            reporters.get(row.user_id).name if reporters.get(row.user_id) else None
                        ),
                        reason=row.reason,
                        created_at=row.created_at,
                    )
                    for row in reports_by_review.get(r.id, [])
                ],
                is_visible=r.is_visible,
                created_at=r.created_at,
            )
        )

    return ReportedReviewListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/reviews/{review_id}", response_model=StatusResponse)
def admin_delete_review(
    review_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> StatusResponse:
    """Delete a review (admin only)."""
    _require_admin(current_user)

    review = db.query(ModelReview).filter(ModelReview.id == review_id).first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    model_id = review.model_project_id
    db.delete(review)

    # Recalculate the listing's rolled-up average.
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id)
        .first()
    )
    if listing:
        all_ratings = (
            db.query(ModelReview.rating)
            .filter(
                ModelReview.model_project_id == model_id,
                ModelReview.is_visible == True,  # noqa: E712
            )
            .all()
        )

        if all_ratings:
            listing.avg_rating = sum(r[0] for r in all_ratings) / len(all_ratings)
        else:
            listing.avg_rating = None

    db.commit()

    return StatusResponse(status="deleted")


@router.patch("/reviews/{review_id}/visibility", response_model=ReviewVisibilityResponse)
def toggle_review_visibility(
    review_id: str,
    db: DBSession,
    visible: bool = Query(...),
    current_user: User = Depends(get_current_user),
) -> ReviewVisibilityResponse:
    """Toggle review visibility (admin only)."""
    _require_admin(current_user)

    review = db.query(ModelReview).filter(ModelReview.id == review_id).first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_visible = visible
    review.is_reported = False  # Clear report flag
    # The reports asked for a decision and have just had one. Leaving the rows
    # behind would put the review back in the queue the next time anybody counts
    # them, and would let one old report stand for a complaint already answered.
    db.query(ModelReviewReport).filter(ModelReviewReport.review_id == review.id).delete(
        synchronize_session=False
    )
    db.commit()

    return ReviewVisibilityResponse(status="updated", is_visible=visible)
