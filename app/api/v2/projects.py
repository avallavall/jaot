"""ModelProject API (P1a) — first-class model entity, commit-grade versions, solve.

The project solve routes through the SAME ``SolveOrchestrator.solve_single`` as the
universal ``/solve`` endpoint (no parallel solve path), tagging the run with
``source_kind="model_project"`` provenance and the typed
``model_project_id``/``model_project_version_id`` columns.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentOrg,
    CurrentUser,
    DBSession,
    OptionalRequireEditor,
    OptionalRequireSolver,
    OptionalRequireViewer,
)
from app.api.v2.solve import _enforce_tier_caps, calculate_credits
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.services.pool import get_solver_pool
from app.models.audit_log import AuditAction
from app.models.builder_document import ModelBuilderDocument
from app.models.model_project import ModelProject, ModelProjectVersion
from app.models.optimization_model import ModelExecution
from app.schemas.model_project import (
    CommitRequest,
    DraftUpdate,
    ProjectCreate,
    ProjectExecutionItem,
    ProjectListItem,
    ProjectMetaUpdate,
    ProjectRead,
    VersionDiff,
    VersionRead,
    VersionSummary,
)
from app.schemas.model_stats import ModelStats
from app.schemas.optimization import OptimizationProblem, OptimizationResult
from app.services import model_project_service as svc
from app.services.audit_service import log_action
from app.services.model_project_service import ProjectConflictError
from app.services.model_stats_service import compute_cached
from app.services.solve_orchestrator import (
    ORIGIN_VISUAL_BUILDER,
    ExecutionSource,
    SolveOrchestrator,
    validate_problem,
)
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_or_404(db: DBSession, project_id: str, org_id: str):
    project = svc.get_project_or_404(db, project_id, org_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_model_project",
)
def create_model_project(
    body: ProjectCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireSolver,
) -> ModelProject:
    """Create a new blank ModelProject for the current organization."""
    project = svc.create_blank(
        db,
        org_id=org.id,
        user_id=user.id,
        name=body.name,
        description=body.description,
        workspace_id=body.workspace_id,
    )
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_EDIT,
        target_type="model_project",
        target_id=project.id,
        target_name=project.name,
    )
    db.commit()
    db.refresh(project)
    return project


@router.post(
    "/from-builder/{document_id}",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_model_project_from_builder",
)
def create_from_builder(
    document_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireSolver,
) -> ModelProject:
    """Seed a ModelProject from an existing builder document (migration helper)."""
    doc = (
        db.query(ModelBuilderDocument)
        .filter(
            ModelBuilderDocument.id == document_id,
            ModelBuilderDocument.organization_id == org.id,
            ModelBuilderDocument.is_active.is_(True),
        )
        .first()
    )
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Builder document not found"
        )
    project = svc.create_seeded(
        db,
        org_id=org.id,
        user_id=user.id,
        name=doc.name,
        problem_json=doc.model_json,
        canvas_json=doc.canvas_json,
        source_type="builder_document",
        source_ref=doc.id,
        auto_commit_summary="Imported from builder document" if doc.model_json else None,
    )
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectListItem], operation_id="list_model_projects")
def list_model_projects(
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireViewer,
    status_filter: str | None = Query("active", alias="status"),
    workspace_id: str | None = Query(None),
    q: str | None = Query(None),
    mine: bool = Query(False),
    skip: int = 0,
    limit: int = 50,
) -> list[ModelProject]:
    """List the organization's ModelProjects (newest-updated first).

    The list is org-wide (collaborative); pass ``mine=true`` to narrow it to the
    current user's own models.
    """
    return svc.list_projects(
        db,
        org_id=org.id,
        status=status_filter,
        workspace_id=workspace_id,
        q=q,
        created_by=user.id if mine else None,
        skip=skip,
        limit=limit,
    )


@router.get("/{project_id}", response_model=ProjectRead, operation_id="get_model_project")
def get_model_project(
    project_id: str, db: DBSession, org: CurrentOrg, _ws: OptionalRequireViewer
) -> ModelProject:
    """Get a single ModelProject (metadata + draft + committed HEAD)."""
    return _project_or_404(db, project_id, org.id)


@router.get("/{project_id}/stats", response_model=ModelStats, operation_id="get_model_stats")
def get_model_stats(
    project_id: str, db: DBSession, org: CurrentOrg, _ws: OptionalRequireViewer
) -> ModelStats:
    """Live structural statistics + health score for the project's working draft."""
    project = _project_or_404(db, project_id, org.id)
    return compute_cached(project.draft_model_json)


# --------------------------------------------------------------------------- #
# Executions — the SERVER-DERIVED source of truth for solve reconciliation (§14)
# --------------------------------------------------------------------------- #
@router.get(
    "/{project_id}/executions",
    response_model=list[ProjectExecutionItem],
    operation_id="list_project_executions",
)
def list_project_executions(
    project_id: str,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireViewer,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
) -> list[ModelExecution]:
    """Executions for this project (newest first).

    This is the server-side anchor that lets the workspace RECONCILE a solve on
    open instead of trusting browser memory: a still-running async run can be
    re-attached by its ``celery_task_id``, and a finished one surfaces as the
    "last run". Matches BOTH provenance shapes a project solve can carry — the
    typed ``model_project_id`` column (the ``/projects/{id}/solve`` path) and the
    generic ``source_kind="model_project"`` provenance (the universal
    ``/solve/async`` path the studio uses for live streaming) — so no solve
    entry point has to change (see the solve-contract-drift safeguard).
    """
    _project_or_404(db, project_id, org.id)
    query = db.query(ModelExecution).filter(
        ModelExecution.organization_id == org.id,
        or_(
            ModelExecution.model_project_id == project_id,
            and_(
                ModelExecution.source_kind == "model_project",
                ModelExecution.source_id == project_id,
            ),
        ),
    )
    if status_filter:
        query = query.filter(ModelExecution.status == status_filter)
    return query.order_by(ModelExecution.created_at.desc()).limit(limit).all()


@router.patch("/{project_id}", response_model=ProjectRead, operation_id="update_model_project")
def update_model_project(
    project_id: str,
    body: ProjectMetaUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelProject:
    """Patch project metadata (name / description / status)."""
    project = _project_or_404(db, project_id, org.id)
    svc.update_meta(db, project, name=body.name, description=body.description, status=body.status)
    db.commit()
    db.refresh(project)
    return project


@router.delete(
    "/{project_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="archive_model_project"
)
def archive_model_project(
    project_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
    permanent: bool = Query(False),
) -> None:
    """Archive a ModelProject (soft-delete), or permanently delete it.

    Default is a reversible **archive** (``status="archived"``). With
    ``?permanent=true`` the project and its versions are **hard-deleted**
    (irreversible) — only allowed once the project is already archived, so a
    permanent delete is always a deliberate two-step action from the trash view.
    """
    project = _project_or_404(db, project_id, org.id)
    if permanent:
        if project.status != "archived":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Archive the project before deleting it permanently.",
            )
        name = project.name
        pid = project.id
        svc.hard_delete_project(db, project)
        log_action(
            db=db,
            organization_id=org.id,
            actor=user,
            action=AuditAction.MODEL_DELETE,
            target_type="model_project",
            target_id=pid,
            target_name=name,
        )
        db.commit()
        return
    svc.archive_project(db, project)
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_DELETE,
        target_type="model_project",
        target_id=project.id,
        target_name=project.name,
    )
    db.commit()


@router.put(
    "/{project_id}/draft", response_model=ProjectRead, operation_id="update_model_project_draft"
)
def update_model_project_draft(
    project_id: str,
    body: DraftUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> ModelProject:
    """Replace the mutable HEAD draft (optimistic concurrency via ``If-Match``)."""
    project = _project_or_404(db, project_id, org.id)
    expected_lock: int | None = None
    if if_match is not None:
        try:
            expected_lock = int(if_match)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="If-Match must be an integer"
            ) from exc
    try:
        svc.update_draft(
            db,
            project,
            model_json=body.model_json_,
            canvas_json=body.canvas_json,
            dsl_source=body.dsl_source,
            expected_lock=expected_lock,
        )
    except ProjectConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(project)
    return project


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #
@router.post(
    "/{project_id}/commit",
    response_model=VersionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="commit_model_version",
)
def commit_model_version(
    project_id: str,
    body: CommitRequest,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelProjectVersion:
    """Commit the current draft as an immutable, message-bearing version."""
    project = _project_or_404(db, project_id, org.id)
    version = svc.commit_version(db, project, user_id=user.id, summary=body.summary, body=body.body)
    db.commit()
    db.refresh(version)
    return version


@router.get(
    "/{project_id}/versions",
    response_model=list[VersionSummary],
    operation_id="list_project_versions",
)
def list_project_versions(
    project_id: str,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireViewer,
    skip: int = 0,
    limit: int = 50,
) -> list[ModelProjectVersion]:
    """List a project's committed versions (newest first)."""
    _project_or_404(db, project_id, org.id)
    return svc.list_versions(db, project_id, org.id, skip=skip, limit=limit)


@router.get(
    "/{project_id}/versions/{version_id}",
    response_model=VersionRead,
    operation_id="get_project_version",
)
def get_project_version(
    project_id: str, version_id: str, db: DBSession, org: CurrentOrg, _ws: OptionalRequireViewer
) -> ModelProjectVersion:
    """Fetch a full committed version snapshot."""
    version = svc.get_version_or_404(db, project_id, version_id, org.id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return version


@router.get(
    "/{project_id}/versions/{a}/diff/{b}",
    response_model=VersionDiff,
    operation_id="diff_project_versions",
)
def diff_project_versions(
    project_id: str, a: str, b: str, db: DBSession, org: CurrentOrg, _ws: OptionalRequireViewer
) -> VersionDiff:
    """Structural diff between two committed versions of a project."""
    va = svc.get_version_or_404(db, project_id, a, org.id)
    vb = svc.get_version_or_404(db, project_id, b, org.id)
    if va is None or vb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return svc.diff_versions(va, vb)


@router.post(
    "/{project_id}/versions/{version_id}/restore",
    response_model=ProjectRead,
    operation_id="restore_project_version",
)
def restore_project_version(
    project_id: str,
    version_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
    discard_draft: bool = Query(False),
) -> ModelProject:
    """Check a committed version out into the draft (history untouched)."""
    project = _project_or_404(db, project_id, org.id)
    version = svc.get_version_or_404(db, project_id, version_id, org.id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    try:
        svc.checkout_into_draft(db, project, version, discard_draft=discard_draft)
    except ProjectConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(project)
    return project


# --------------------------------------------------------------------------- #
# Solve (routes through the single SolveOrchestrator path)
# --------------------------------------------------------------------------- #
@router.post(
    "/{project_id}/solve", response_model=OptimizationResult, operation_id="solve_model_project"
)
async def solve_model_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    version_id: str | None = Query(default=None),
    solver_name: str | None = Query(default=None, max_length=32),
) -> OptimizationResult:
    """Solve a ModelProject's draft (or a specific committed version).

    Mirrors the universal ``/solve`` flow exactly — tier caps, auto-routing,
    credit calc, and ``SolveOrchestrator.solve_single`` — adding only the
    ``model_project`` provenance + typed project/version columns on the row.
    """
    org = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    project = _project_or_404(db, project_id, org.id)

    mpv_id: str | None = None
    if version_id:
        version = svc.get_version_or_404(db, project_id, version_id, org.id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        model_json = version.model_json
        mpv_id = version.id
    else:
        model_json = project.draft_model_json

    if not model_json:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project has no model to solve.",
        )

    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    try:
        problem = OptimizationProblem.model_validate(model_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stored model is not a valid optimization problem: {exc.errors()[:3]}",
        ) from exc

    problem = _enforce_tier_caps(db, org, problem)

    requested_solver_name = problem.solver_name or solver_name
    auto_route_reason: str | None = None
    fallback_triggered = False
    if requested_solver_name == "auto":
        from app.domains.solver.services.auto_router import select_solver  # noqa: PLC0415

        effective_solver_name, auto_route_reason, fallback_triggered = select_solver(
            problem, solver.parser
        )
    else:
        effective_solver_name = requested_solver_name

    ensure_hexaly_worker_or_503(effective_solver_name)

    base_credits = calculate_credits(problem, solver_name=effective_solver_name, db=db)
    credits_needed = max(1, round(base_credits * 0.5)) if problem.warm_start else base_credits

    validate_problem(problem)

    ws_id = workspace_member.workspace_id if workspace_member else None
    user = getattr(request.state, "user", None)

    orchestrator = SolveOrchestrator(db, solver, get_solver_pool())
    try:
        result = await orchestrator.solve_single(
            problem=problem,
            org=org,
            user=user,
            request=request,
            credits_needed=credits_needed,
            workspace_id=ws_id,
            solver_name=effective_solver_name,
            auto_route_reason=auto_route_reason,
            source=ExecutionSource.from_request(ORIGIN_VISUAL_BUILDER, "model_project", project.id),
            model_project_id=project.id,
            model_project_version_id=mpv_id,
        )
    except (SolverNotFoundError, SolverUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    result.solver_used = effective_solver_name or DEFAULT_SOLVER_NAME
    result.auto_route_reason = auto_route_reason
    if fallback_triggered:
        result.warning = (
            "Hexaly temporarily unavailable; solved with SCIP (quadratic quality may differ)"
        )
    return result
