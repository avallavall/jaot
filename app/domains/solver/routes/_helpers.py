"""Shared helpers for solve route endpoints."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ModelExecution
from app.schemas.optimization import OptimizationProblem
from app.shared.core.http_errors import CodedHTTPException


def load_execution(db: Session, execution_id: str, org_id: str) -> ModelExecution:
    """Load an execution with org-scoped access check.

    Raises:
        HTTPException 404 if not found or not owned by org.
    """
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == org_id,
        )
        .first()
    )
    if not execution:
        # English `detail` is the API contract; the code is what a page in
        # another language renders instead of it.
        raise CodedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found.",
            code="execution.not_found",
        )
    return execution


def parse_problem(execution: ModelExecution) -> OptimizationProblem:
    """Reconstruct OptimizationProblem from stored input_data.

    Raises:
        HTTPException 422 if input_data is missing or invalid.
    """
    input_data = execution.input_data
    if not input_data or not isinstance(input_data, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Execution has no stored problem data.",
        )
    try:
        return OptimizationProblem(**input_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot reconstruct problem from stored data: {exc}",
        ) from exc
