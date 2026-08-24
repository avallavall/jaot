"""Insights endpoint for optimization executions.

Returns auto-generated analysis of a solve result.

  GET /insights/{execution_id}
"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.domains.solver.routes._helpers import load_execution
from app.domains.solver.services.insights import InsightCategory, InsightSeverity, generate_insights
from app.schemas.optimization import OptimizationProblem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights")


class InsightResponse(BaseModel):
    """Single insight in the API response."""

    category: InsightCategory
    message: str
    severity: InsightSeverity
    #: Stable identifier a localized interface renders instead of `message`,
    #: which stays English for API and MCP clients. Empty for none.
    code: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class InsightsResponse(BaseModel):
    """Response for the insights endpoint."""

    execution_id: str
    insights: list[InsightResponse]


@router.get(
    "/{execution_id}",
    response_model=InsightsResponse,
    operation_id="get_execution_insights",
)
def get_execution_insights(
    execution_id: str,
    current_user: CurrentUser,
    org: CurrentOrg,
    db: DBSession,
) -> InsightsResponse:
    """Generate auto-insights for a completed execution."""
    execution = load_execution(db, execution_id, org, current_user)

    input_data = execution.problem_data
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
                code=i.code,
                params=i.params,
            )
            for i in raw_insights
        ],
    )
