"""Shared helpers for solve route endpoints."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import enforce_execution_workspace
from app.models import ModelExecution, Organization, User
from app.schemas.optimization import OptimizationProblem
from app.shared.core.http_errors import CodedHTTPException


def load_execution(
    db: Session, execution_id: str, org: Organization, user: User | None
) -> ModelExecution:
    """Load an execution owned by ``org`` and behind its model's workspace.

    ``user`` has no default on purpose. The organization filter alone let
    anybody in the organization read the insights of a run of a model filed in
    a workspace they are not in, and export the whole problem from it.

    Raises:
        HTTPException 404 if not found or not owned by org, 403 if the model it
        ran is filed in a workspace the caller is not a member of.
    """
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == org.id,
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
    enforce_execution_workspace(db, execution, user, org)
    return execution


def parse_problem(execution: ModelExecution) -> OptimizationProblem:
    """Reconstruct OptimizationProblem from the problem this run solved.

    Raises:
        HTTPException 422 if the problem is missing or invalid.
    """
    input_data = execution.problem_data
    if not input_data:
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
