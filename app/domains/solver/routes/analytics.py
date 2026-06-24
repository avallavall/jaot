"""Cross-execution analytics endpoints.

Provides aggregate statistics, time-series trends, and execution
comparison for an organization's solve history.

  GET /analytics/summary?days=30
  GET /analytics/trends?days=30&bucket=day
  GET /analytics/compare?ids=exe_1,exe_2
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.domains.solver.services.analytics import (
    BucketSize,
    compare_executions,
    compute_summary,
    compute_trends,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics")


class SummaryResponse(BaseModel):
    """Aggregated execution statistics."""

    total_executions: int
    completed: int
    failed: int
    timed_out: int
    success_rate: float
    avg_solve_time_ms: float | None
    median_solve_time_ms: float | None
    total_credits: int
    avg_credits: float
    avg_objective_value: float | None
    executions_by_status: dict[str, int]
    executions_by_origin: dict[str, int]
    solver_status_distribution: dict[str, int]


class TrendBucketResponse(BaseModel):
    """A single time-bucket in a trend series."""

    date: str
    executions: int
    completed: int
    failed: int
    credits: int
    avg_solve_time_ms: float | None


class TrendsResponse(BaseModel):
    """Time-series trend data."""

    days: int
    bucket: str
    data: list[TrendBucketResponse]


class ComparedExecutionResponse(BaseModel):
    """A single execution in a comparison set."""

    id: str
    status: str
    solver_status: str | None
    objective_value: float | None
    execution_time_ms: int | None
    credits_consumed: int
    created_at: str
    origin: str
    num_variables: int | None
    num_constraints: int | None
    gap: float | None


class CompareResponse(BaseModel):
    """Side-by-side execution comparison."""

    executions: list[ComparedExecutionResponse]


@router.get(
    "/summary",
    response_model=SummaryResponse,
    operation_id="get_analytics_summary",
)
async def get_analytics_summary(
    current_user: CurrentUser,
    org: CurrentOrg,
    db: DBSession,
    days: int = Query(30, ge=0, le=365, description="Look-back window (0 = all time)"),
) -> SummaryResponse:
    """Aggregated execution statistics for the organization."""
    summary = compute_summary(db, org.id, days)
    return SummaryResponse(
        total_executions=summary.total_executions,
        completed=summary.completed,
        failed=summary.failed,
        timed_out=summary.timed_out,
        success_rate=summary.success_rate,
        avg_solve_time_ms=summary.avg_solve_time_ms,
        median_solve_time_ms=summary.median_solve_time_ms,
        total_credits=summary.total_credits,
        avg_credits=summary.avg_credits,
        avg_objective_value=summary.avg_objective_value,
        executions_by_status=summary.executions_by_status,
        executions_by_origin=summary.executions_by_origin,
        solver_status_distribution=summary.solver_status_distribution,
    )


@router.get(
    "/trends",
    response_model=TrendsResponse,
    operation_id="get_analytics_trends",
)
async def get_analytics_trends(
    current_user: CurrentUser,
    org: CurrentOrg,
    db: DBSession,
    days: int = Query(30, ge=0, le=365, description="Look-back window (0 = all time)"),
    bucket: BucketSize = Query("day", description="Aggregation bucket: day or week"),
) -> TrendsResponse:
    """Time-series trend data for the organization's executions."""
    trend_data = compute_trends(db, org.id, days, bucket)
    return TrendsResponse(
        days=days,
        bucket=bucket,
        data=[
            TrendBucketResponse(
                date=t.date,
                executions=t.executions,
                completed=t.completed,
                failed=t.failed,
                credits=t.credits,
                avg_solve_time_ms=t.avg_solve_time_ms,
            )
            for t in trend_data
        ],
    )


@router.get(
    "/compare",
    response_model=CompareResponse,
    operation_id="compare_executions",
)
async def compare_executions_endpoint(
    current_user: CurrentUser,
    org: CurrentOrg,
    db: DBSession,
    ids: str = Query(..., description="Comma-separated execution IDs (max 10)"),
) -> CompareResponse:
    """Compare multiple executions side-by-side."""
    execution_ids = [eid.strip() for eid in ids.split(",") if eid.strip()]
    if len(execution_ids) > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Maximum 10 execution IDs allowed.",
        )
    compared = compare_executions(db, org.id, execution_ids)
    return CompareResponse(
        executions=[
            ComparedExecutionResponse(
                id=c.id,
                status=c.status,
                solver_status=c.solver_status,
                objective_value=c.objective_value,
                execution_time_ms=c.execution_time_ms,
                credits_consumed=c.credits_consumed,
                created_at=c.created_at,
                origin=c.origin,
                num_variables=c.num_variables,
                num_constraints=c.num_constraints,
                gap=c.gap,
            )
            for c in compared
        ],
    )
