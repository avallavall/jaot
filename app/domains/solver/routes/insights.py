"""Insights endpoint for optimization executions.

Returns auto-generated analysis of a solve result.

  GET /insights/{execution_id}
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentOrg, CurrentUser
from app.domains.solver.routes._helpers import load_execution
from app.domains.solver.services.insights import InsightCategory, InsightSeverity, generate_insights
from app.schemas.optimization import OptimizationProblem
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights")


class InsightResponse(BaseModel):
    """Single insight in the API response."""

    category: InsightCategory
    message: str
    severity: InsightSeverity


class InsightsResponse(BaseModel):
    """Response for the insights endpoint."""

    execution_id: str
    insights: list[InsightResponse]


@router.get(
    "/{execution_id}",
    response_model=InsightsResponse,
    operation_id="get_execution_insights",
)
async def get_execution_insights(
    execution_id: str,
    current_user: CurrentUser,
    org: CurrentOrg,
    db: Session = Depends(get_db),
) -> InsightsResponse:
    """Generate auto-insights for a completed execution."""
    execution = load_execution(db, execution_id, org.id)

    input_data = execution.input_data
    if not input_data or not isinstance(input_data, dict):
        return InsightsResponse(execution_id=execution_id, insights=[])

    try:
        problem = OptimizationProblem(**input_data)
    except Exception:
        return InsightsResponse(execution_id=execution_id, insights=[])

    result_data = execution.result_data or {}
    raw_insights = generate_insights(problem, result_data)

    return InsightsResponse(
        execution_id=execution_id,
        insights=[
            InsightResponse(
                category=i.category,
                message=i.message,
                severity=i.severity,
            )
            for i in raw_insights
        ],
    )
