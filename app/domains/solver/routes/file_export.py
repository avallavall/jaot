"""File export endpoints for optimization executions.

Allows users to download their solved problems and solutions in
standard formats: MPS, LP, CIP, SOL, CSV, JSON.

  GET /export/{execution_id}/{format}
"""

import io
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.deps import CurrentOrg, CurrentUser
from app.domains.solver.routes._helpers import load_execution, parse_problem
from app.domains.solver.services.file_export import (
    ALL_EXPORT_FORMATS,
    MIME_TYPES,
    SOLVER_FORMATS,
    FileExportError,
    get_file_export_service,
)
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export")


def _safe_filename(name: str, ext: str) -> str:
    """Generate a safe filename for Content-Disposition."""
    clean = re.sub(r"[^\w\-]", "_", name or "problem")[:80]
    return f"{clean}.{ext}"


@router.get(
    "/{execution_id}/{fmt}",
    operation_id="export_execution",
    response_model=None,
    responses={
        200: {"description": "File download"},
        404: {"description": "Execution not found"},
        422: {"description": "Cannot export (missing data or invalid format)"},
    },
)
async def export_execution(
    execution_id: str,
    fmt: str,
    current_user: CurrentUser,
    org: CurrentOrg,
    db: Session = Depends(get_db),
) -> FileResponse | StreamingResponse:
    """Export an execution's problem or solution in the requested format.

    Solver formats (mps, lp, cip) rebuild the SCIP model and write to file.
    Text formats (sol, csv, json) are generated in memory.
    """
    fmt = fmt.lower().strip()
    if fmt not in ALL_EXPORT_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported format: '{fmt}'. Supported: {', '.join(sorted(ALL_EXPORT_FORMATS))}",
        )

    execution = load_execution(db, execution_id, org.id)
    problem = parse_problem(execution)
    exporter = get_file_export_service()

    problem_name = problem.name or execution_id

    # --- Solver formats: write to temp file, stream back ---
    if fmt in SOLVER_FORMATS:
        try:
            tmp_path = exporter.export_to_file(problem, fmt)
        except FileExportError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

        return FileResponse(
            path=tmp_path,
            filename=_safe_filename(problem_name, fmt),
            media_type=MIME_TYPES[fmt],
            background=BackgroundTask(os.unlink, tmp_path),
        )

    # --- Text formats: generate in memory ---
    result_data = execution.result_data or {}

    if fmt == "sol":
        try:
            content = exporter.export_solution_sol(problem, result_data)
        except FileExportError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return StreamingResponse(
            content=io.BytesIO(content.encode("utf-8")),
            media_type=MIME_TYPES["sol"],
            headers={
                "Content-Disposition": f'attachment; filename="{_safe_filename(problem_name, "sol")}"',
            },
        )

    if fmt == "csv":
        try:
            content = exporter.export_solution_csv(problem, result_data)
        except FileExportError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        # UTF-8 BOM for Excel compatibility
        bom = b"\xef\xbb\xbf"
        return StreamingResponse(
            content=io.BytesIO(bom + content.encode("utf-8")),
            media_type=MIME_TYPES["csv"],
            headers={
                "Content-Disposition": f'attachment; filename="{_safe_filename(problem_name, "csv")}"',
            },
        )

    # fmt == "json"
    content = exporter.export_json(problem, result_data)
    return StreamingResponse(
        content=io.BytesIO(content.encode("utf-8")),
        media_type=MIME_TYPES["json"],
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_filename(problem_name, "json")}"',
        },
    )
