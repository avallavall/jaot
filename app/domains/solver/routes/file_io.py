"""File import endpoints for optimization models.

Allows users to upload MPS, LP, CIP, or JSON files and either:
  - Preview the parsed problem (POST /import/preview)
  - Import and solve directly (POST /import)
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentOrg, CurrentUser
from app.api.v2.solve import (
    _enqueue_async_solve,
    _shape_sync_result,
    _wait_for_task,
)
from app.domains.solver.services.file_import import (
    FileImportError,
    get_file_import_service,
    validate_extension,
)
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
from app.services.solve_orchestrator import ORIGIN_IMPORT
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import")


def _read_upload_sync(file: UploadFile) -> bytes:
    """Blocking read of an upload for a sync (threadpool) handler.

    Both handlers in this module are sync ``def``: ``import_and_solve`` because it
    blocks on the queued solve result (ADR-007 S4a), ``import_preview`` because
    parsing the file is CPU-bound (ADR-009). Reading the already-spooled multipart
    file directly is safe — Starlette has fully buffered the upload before the
    handler runs — and it is what lets the whole handler live in the threadpool.
    (The async twin this replaced had no callers left once both went sync.)
    """
    return _validate_upload_bytes(file.file.read())


def _validate_upload_bytes(content: bytes) -> bytes:
    """Shared size/empty guard for both the async and sync upload readers."""
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
        file_size_bytes=len(file_bytes),
        original_filename=filename,
    )


@router.post(
    "/preview",
    response_model=FileImportPreviewResponse,
    operation_id="import_preview",
)
def import_preview(  # sync ON PURPOSE -> threadpool (ADR-009): parses the whole file
    file: UploadFile,
    current_user: CurrentUser,
    org: CurrentOrg,
    objective_sense: ObjectiveSense | None = Form(default=None),
) -> FileImportPreviewResponse:
    """Parse an uploaded optimization file and return a preview.

    Does NOT solve. Use this to inspect the imported
    problem before committing to a solve.

    Sync like its ``import_and_solve`` sibling: parsing an MPS/LP is CPU-bound and
    the upload cap is tens of megabytes, so on the event loop it stalled every other
    request for the duration of the parse. Reads the already-spooled file directly
    (see ``_read_upload_sync``).
    """
    file_bytes = _read_upload_sync(file)
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
def import_and_solve(  # def: blocks on the queued result in the threadpool (ADR-007 S4a)
    file: UploadFile,
    current_user: CurrentUser,
    org: CurrentOrg,
    db: Session = Depends(get_db),
    time_limit_seconds: float = Form(default=60.0, ge=1, le=3600),
    gap_tolerance: float = Form(default=0.0001, ge=0, le=1),
    objective_sense: ObjectiveSense | None = Form(default=None),
    solver_name: str | None = Form(default=None, max_length=32),
) -> Any:
    """Import an optimization file and solve it.

    ADR-007 S4a — async-under-the-hood: parses the uploaded file + applies solver
    options server-side, then rides the ONE async pipeline
    (``_enqueue_async_solve``) exactly like ``POST /solve`` — tier caps,
    auto-routing, the pending
    ModelExecution row (tagged ``imported_file`` provenance), and the Celery
    worker. The classic ``OptimizationResult`` comes back on completion; a solve
    that outlives the wait budget returns 202 + the task envelope (poll/subscribe).
    """
    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    file_bytes = _read_upload_sync(file)
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

    enqueued = _enqueue_async_solve(
        db=db,
        org=org,
        user=current_user,
        problem=problem,
        workspace_id=None,
        solver_name_param=solver_name,
        origin=ORIGIN_IMPORT,
        source_kind="imported_file",
        source_id=None,
        dataset_id=None,
    )
    payload = _wait_for_task(enqueued.task)
    if payload is None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                **enqueued.envelope,
                "message": (
                    "Solve still running after the wait budget — poll poll_url or "
                    "subscribe to ws_url for the result."
                ),
            },
        )
    return _shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=enqueued.execution_id,
        solver_used=enqueued.effective_solver,
        auto_route_reason=enqueued.auto_route_reason,
        fallback_triggered=enqueued.fallback_triggered,
    )
