"""The rolled-up rating of a marketplace listing, computed one way everywhere.

Four routes change a listing's reviews: writing one, deleting your own, and an
admin deleting or hiding one. Each kept its own copy of the average. The admin
delete read the reviews before its DELETE was flushed (production sessions do
not autoflush), so the deleted rating stayed in the average; hiding a review
never recomputed it at all; and two reviews written at the same moment each
averaged without the other, the last commit winning.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ModelProjectListing, ModelReview


def recompute_avg_rating(db: Session, model_id: str) -> None:
    """Set the listing's ``avg_rating`` from its visible reviews (None when there are none).

    Flushes first, so a delete or a visibility change made in this transaction
    is part of the count. Locks the listing row, so concurrent review writes
    take turns and each one averages every committed review. Does not commit.
    """
    db.flush()
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id)
        .with_for_update()
        .first()
    )
    if listing is None:
        return
    average = (
        db.query(func.avg(ModelReview.rating))
        .filter(
            ModelReview.model_project_id == model_id,
            ModelReview.is_visible == True,  # noqa: E712
        )
        .scalar()
    )
    # ``func.avg`` returns Decimal on PostgreSQL.
    listing.avg_rating = float(average) if average is not None else None
