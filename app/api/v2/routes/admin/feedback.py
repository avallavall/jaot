"""Admin feedback analytics endpoints."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, case, cast, func
from sqlalchemy.orm import Session

from app.models.formulation_rating import FormulationRating
from app.schemas.feedback import (
    DailyTrend,
    FeedbackListResponse,
    FeedbackStatsResponse,
    RatingResponse,
    ZoneStats,
)
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-feedback"])


@router.get("/feedback", response_model=FeedbackListResponse)
def list_feedback(
    zone: str | None = None,
    rating: str | None = None,
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedbackListResponse:
    """List feedback ratings with optional filters (zone, rating, date range)."""
    cutoff = (utcnow() - timedelta(days=days)).replace(tzinfo=None)

    query = (
        db.query(FormulationRating)
        .filter(FormulationRating.created_at >= cutoff)
        .order_by(FormulationRating.created_at.desc())
    )

    if zone:
        query = query.filter(FormulationRating.zone == zone)
    if rating:
        query = query.filter(FormulationRating.rating == rating)

    items, total = paginate_query(query, page=page, page_size=page_size)

    return FeedbackListResponse(
        items=[RatingResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total > 0 else 0,
    )


@router.get("/feedback/stats", response_model=FeedbackStatsResponse)
def feedback_stats(
    zone: str | None = None,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> FeedbackStatsResponse:
    """Aggregate feedback statistics: totals, by-zone, avg_rating, daily_trend."""
    cutoff = (utcnow() - timedelta(days=days)).replace(tzinfo=None)

    base_query = db.query(FormulationRating).filter(FormulationRating.created_at >= cutoff)
    if zone:
        base_query = base_query.filter(FormulationRating.zone == zone)

    # --- Overall counts ---
    counts = base_query.with_entities(
        func.count().label("total"),
        func.count(case((FormulationRating.rating == "up", 1))).label("up"),
        func.count(case((FormulationRating.rating == "down", 1))).label("down"),
    ).one()

    total = counts.total or 0
    up = counts.up or 0
    down = counts.down or 0
    avg_rating = round(up / total, 4) if total > 0 else 0.0

    # --- By-zone breakdown ---
    zone_rows = (
        base_query.with_entities(
            FormulationRating.zone,
            func.count().label("total"),
            func.count(case((FormulationRating.rating == "up", 1))).label("up"),
            func.count(case((FormulationRating.rating == "down", 1))).label("down"),
        )
        .group_by(FormulationRating.zone)
        .all()
    )

    by_zone = [
        ZoneStats(zone=row.zone, total=row.total, up=row.up, down=row.down) for row in zone_rows
    ]

    # --- Daily trend ---
    daily_rows = (
        base_query.with_entities(
            cast(FormulationRating.created_at, Date).label("day"),
            func.count().label("total"),
            func.count(case((FormulationRating.rating == "up", 1))).label("up"),
            func.count(case((FormulationRating.rating == "down", 1))).label("down"),
        )
        .group_by(cast(FormulationRating.created_at, Date))
        .order_by(cast(FormulationRating.created_at, Date).asc())
        .all()
    )

    daily_trend = [
        DailyTrend(
            date=row.day.isoformat(),
            total=row.total,
            up=row.up,
            down=row.down,
        )
        for row in daily_rows
    ]

    return FeedbackStatsResponse(
        total=total,
        up=up,
        down=down,
        avg_rating=avg_rating,
        by_zone=by_zone,
        daily_trend=daily_trend,
        period_days=days,
    )
