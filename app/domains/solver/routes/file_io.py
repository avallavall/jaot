"""File import endpoints for optimization models.

Allows users to upload MPS, LP, CIP, or JSON files and either:
  - Preview the parsed problem (POST /import/preview)
  - Import and solve directly (POST /import)
"""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentOrg, CurrentUser
from app.api.v2.solve import _enforce_tier_caps, calculate_credits
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.services import get_solver_service
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.services.file_import import (
    FileImportError,
    get_file_import_service,
    validate_extension,
)
from app.domains.solver.services.pool import get_solver_pool
from app.schemas.file_io import (
    MAX_IMPORT_SIZE,
    FileImportMetadata,
    FileImportPreviewResponse,
)
from app.schemas.optimization import (
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    VariableType,
)
from app.services.solve_orchestrator import SolveOrchestrator, validate_problem
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import")


async def _read_upload(file: UploadFile) -> bytes:
    """Read upload file bytes with size validation."""
    content = await file.read()
    if len(content) > MAX_IMPORT_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File too large: {len(content)} bytes. "
                f"Maximum: {MAX_IMPORT_SIZE // (1024 * 1024)} MB."
            ),
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    return content


def _build_metadata(
    problem: OptimizationProblem,
    file_bytes: bytes,
    filename: str,
    extension: str,
) -> FileImportMetadata:
    """Build FileImportMetadata from a parsed OptimizationProblem."""
    num_integer = sum(1 for v in problem.variables if v.type == VariableType.INTEGER)
    num_binary = sum(1 for v in problem.variables if v.type == VariableType.BINARY)
    num_continuous = sum(1 for v in problem.variables if v.type == VariableType.CONTINUOUS)

    # Strip leading dot for a clean format string (e.g. ".mps" → "mps")
    clean_format = extension.lstrip(".")

    return FileImportMetadata(
        source_format=clean_format,
        num_variables=len(problem.variables),
        num_constraints=len(problem.constraints),
        num_integer=num_integer,
        num_binary=num_binary,
        num_continuous=num_continuous,
        # D-02: this builder feeds ONLY /import/preview, which doesn't solve
        # or debit. Estimate is base cost so customers compare workloads
        # independent of solver; multiplier is applied at real debit sites
        # (import_and_solve, /solve, solve_with_template) where solver name
        # is known.
        estimated_credits=calculate_credits(problem),
        file_size_bytes=len(file_bytes),
        original_filename=filename,
    )


@router.post(
    "/preview",
    response_model=FileImportPreviewResponse,
    operation_id="import_preview",
)
async def import_preview(
    file: UploadFile,
    current_user: CurrentUser,
    org: CurrentOrg,
    objective_sense: ObjectiveSense | None = Form(default=None),
) -> FileImportPreviewResponse:
    """Parse an uploaded optimization file and return a preview.

    Does NOT solve or deduct credits. Use this to inspect the imported
    problem before committing to a solve.
    """
    file_bytes = await _read_upload(file)
    filename = file.filename or "unknown"

    importer = get_file_import_service()
    try:
        extension = validate_extension(filename)
        problem = importer.import_from_file(file_bytes, filename, objective_sense)
    except FileImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    metadata = _build_metadata(problem, file_bytes, filename, extension)

    return FileImportPreviewResponse(problem=problem, metadata=metadata)


@router.post(
    "",
    response_model=OptimizationResult,
    operation_id="import_and_solve",
)
async def import_and_solve(
    file: UploadFile,
    request: Request,
    current_user: CurrentUser,
    org: CurrentOrg,
    db: Session = Depends(get_db),
    time_limit_seconds: float = Form(default=60.0, ge=1, le=3600),
    gap_tolerance: float = Form(default=0.0001, ge=0, le=1),
    objective_sense: ObjectiveSense | None = Form(default=None),
    solver_name: str | None = Form(default=None, max_length=32),
) -> OptimizationResult:
    """Import an optimization file and solve it immediately.

    Parses the file, applies solver options, deducts credits, and returns
    the solve result. Follows the same credit/tier/rate-limit flow as
    the standard /solve endpoint.
    """
    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    file_bytes = await _read_upload(file)
    filename = file.filename or "unknown"

    importer = get_file_import_service()
    try:
        problem = importer.import_from_file(file_bytes, filename, objective_sense)
    except FileImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Apply user-specified solver options (immutable copy)
    problem = problem.model_copy(
        update={
            "options": problem.options.model_copy(
                update={
                    "time_limit_seconds": time_limit_seconds,
                    "gap_tolerance": gap_tolerance,
                }
            )
        }
    )

    _enforce_tier_caps(db, org, problem)

    # D-11 / WR-04: direct hexaly + worker down → 503 BEFORE credit debit.
    # Mirrors the gate in app/api/v2/solve.py for canonical error contract
    # instead of the old "deduct → fail → refund → 422" churn.
    effective_solver_for_pricing = solver_name or DEFAULT_SOLVER_NAME
    ensure_hexaly_worker_or_503(effective_solver_for_pricing)

    # PRC-01 / D-02 / WR-01: this route DEBITS credits via orchestrator's
    # solve_single → _pre_pay_credits → deduct_credits — it is NOT a preview.
    # Pass user-selected (or default) solver_name so the multiplier reaches
    # PSS — a Hexaly file-import solve correctly costs 5x credits matching
    # /api/v2/solve.
    credits_needed = calculate_credits(problem, solver_name=effective_solver_for_pricing, db=db)
    validate_problem(problem)

    solver = get_solver_service()
    orchestrator = SolveOrchestrator(db, solver, get_solver_pool())
    try:
        return await orchestrator.solve_single(
            problem=problem,
            org=org,
            user=current_user,
            request=request,
            credits_needed=credits_needed,
            solver_name=solver_name,
        )
    except (SolverNotFoundError, SolverUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
