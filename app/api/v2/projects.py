"""ModelProject API (P1a) — first-class model entity, commit-grade versions, solve.

The project solve rides the SAME async pipeline (``enqueue_async_solve``) as the
universal ``POST /solve`` endpoint (ADR-007: no parallel solve path), tagging the
run with ``source_kind="model_project"`` provenance and the typed
``model_project_id``/``model_project_version_id`` columns.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentOrg,
    CurrentUser,
    DBSession,
    OptionalRequireEditor,
    OptionalRequireSolver,
    OptionalRequireViewer,
    enforce_org_rate_limit,
)
from app.api.v2.deps.solve_maintenance_gate import solve_maintenance_gate
from app.api.v2.solve_pipeline import (
    apply_solution_filter,
    enqueue_async_solve,
    shape_sync_result,
    wait_for_task,
)
from app.domains.dsl import JModelData, JModelError, compile_jmodel
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.template_engine import TemplateEngine, get_template_engine
from app.models import Organization, User
from app.models.audit_log import AuditAction
from app.models.model_project import (
    ModelProject,
    ModelProjectDataset,
    ModelProjectListing,
    ModelProjectVersion,
)
from app.models.optimization_model import ModelExecution
from app.schemas.model import ModelCatalogResponse, PublishModelRequest
from app.schemas.model_project import (
    CommitRequest,
    DatasetCreate,
    DatasetImportPreview,
    DatasetRead,
    DatasetSummary,
    DatasetUpdate,
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
from app.schemas.optimization import (
    AsyncSolveEnvelope,
    OptimizationProblem,
    OptimizationResult,
)
from app.services import model_project_service as svc
from app.services.audit_service import log_action
from app.services.marketplace_fusion import listing_to_catalog_response
from app.services.model_project_service import ProjectConflictError, ProjectNotPublishableError
from app.services.model_stats_service import compute_cached
from app.services.template_resolver import (
    ORIGIN_MARKETPLACE,
    resolve_static_listing,
    resolve_template_dict,
)
from app.shared.constants.execution_provenance import ORIGIN_VISUAL_BUILDER
from app.shared.core.http_errors import CodedHTTPException
from app.shared.core.validation_message import validation_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


class FromMarketplaceRequest(BaseModel):
    """Optional custom input when seeding a generator-backed marketplace model.

    A generator-backed listing (official) renders ``user_input`` instead of its
    ``example_input`` (parametric "use in studio"); a static listing ignores it.
    """

    user_input: dict[str, Any] | None = None

    # MCP-facing body: a wrong argument name must be a 422, never a silent no-op.
    model_config = ConfigDict(extra="forbid")


#: Refusal shown when a write lands on an archived project. One sentence for
#: every route, because a caller that hits two of them must not have to work
#: out whether two different messages mean the same thing.
_ARCHIVED_DETAIL = "This model is archived. Restore it before making changes."


def _project_or_404(db: DBSession, project_id: str, org_id: str):
    project = svc.get_project_or_404(db, project_id, org_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _writable_project_or_404(db: DBSession, project_id: str, org_id: str):
    """Load a project that may be changed, or refuse because it is archived.

    Archiving is this platform's soft delete, and nothing used to enforce it.
    ``get_project_or_404`` returns a project of any status by design, every
    write loaded through it, and so an archived project could still be renamed,
    edited, committed, solved and **published to the public marketplace**. The
    only thing keeping anyone out was the model list rendering an archived row
    without a link; the URL underneath still worked.

    Restoring does not come through here. It is ``PATCH {"status": "active"}``,
    which ``update_model_project`` lets past on its own — otherwise archiving
    would be a door that locks from both sides.

    Reads are untouched. An archived project must stay fully readable, or the
    trash view could not show what is in it.
    """
    project = _project_or_404(db, project_id, org_id)
    if project.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ARCHIVED_DETAIL)
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


def _seed_from_template(
    db: Session,
    *,
    org_id: str,
    user_id: str | None,
    template_engine: TemplateEngine,
    template_id: str,
    source_type: str,
    user_input: dict[str, Any] | None = None,
) -> ModelProject:
    """Resolve a template/marketplace id, materialize it, and seed a ModelProject.

    Shared by the from-template and from-marketplace routes (P2 centralization). Two
    materialization paths (P1.5 fusion):

    * **generator-backed** (YAML template or an official listing) → render through the
      ``TemplateEngine`` with ``user_input`` (or the source's ``example_input`` for a
      one-click start). No new generator code is introduced.
    * **static** published listing (a plain community project) → copy its pinned
      committed version's ``model_json`` directly (nothing to render).

    Either way the new project is born with a v1 commit so it has history from the
    first moment.
    """
    template_dict, _origin = resolve_template_dict(template_id, db)
    if template_dict is not None:
        input_data = (
            user_input if user_input is not None else (template_dict.get("example_input") or {})
        )
        try:
            problem = template_engine.render(template_dict, input_data)
        except Exception as exc:  # noqa: BLE001 — any generator failure → 422, not 500
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not build a model from this template: {exc}",
            ) from exc
        name = template_dict.get("display_name") or template_dict.get("name") or "Untitled Model"
        problem_json = problem.model_dump(mode="json")
        # Normalize the provenance ref to the RESOLVED id — the resolver also
        # matches "official_{id}", so the caller-supplied id may differ from the
        # listing's. Analytics + execute resolve forks through source_ref.
        source_ref = str(template_dict.get("id") or template_id)
    elif source_type == ORIGIN_MARKETPLACE:
        static = resolve_static_listing(template_id, db)
        if static is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        listing, version = static
        problem_json = version.model_json
        name = listing.display_name
        source_ref = listing.model_project_id
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    label = "template" if source_type == "template" else "marketplace model"
    return svc.create_seeded(
        db,
        org_id=org_id,
        user_id=user_id,
        name=name,
        problem_json=problem_json,
        source_type=source_type,
        source_ref=source_ref,
        auto_commit_summary=f"Created from {label} '{name}'",
    )


@router.post(
    "/from-template/{template_id}",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_model_project_from_template",
)
def create_from_template(
    template_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireSolver,
    template_engine: TemplateEngine = Depends(get_template_engine),
) -> ModelProject:
    """Seed a ModelProject from a template (one-click "Use template" → workspace)."""
    project = _seed_from_template(
        db,
        org_id=org.id,
        user_id=user.id,
        template_engine=template_engine,
        template_id=template_id,
        source_type="template",
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
    "/from-marketplace/{model_id}",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_model_project_from_marketplace",
)
def create_from_marketplace(
    model_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireSolver,
    body: FromMarketplaceRequest | None = None,
    template_engine: TemplateEngine = Depends(get_template_engine),
) -> ModelProject:
    """Seed a ModelProject from a published marketplace model → workspace.

    Optional ``user_input`` customizes a generator-backed (official) model instead of
    its example input; a static community model ignores it (its pinned version is copied).

    This is THE "use a marketplace model" path (P1.5 fusion — the legacy activate
    flow collapsed into it), so the adoption side-effects live here: the listing's
    activation counter and the author notification.
    """
    project = _seed_from_template(
        db,
        org_id=org.id,
        user_id=user.id,
        template_engine=template_engine,
        template_id=model_id,
        source_type="marketplace",
        user_input=body.user_input if body else None,
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

    # Adoption side-effects on the source listing (source_ref is the resolved id).
    # SQL-expression assignment → an atomic UPDATE (no lost increments when two
    # orgs fork the same listing concurrently).
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == project.source_ref)
        .first()
    )
    if listing is not None:
        listing.total_activations = ModelProjectListing.total_activations + 1

    db.commit()
    db.refresh(project)

    # Fire-and-forget: usage analytics + author notification (never block seeding).
    try:
        from app.services.analytics_service import AnalyticsService  # noqa: PLC0415
        from app.shared.constants import event_types as evt  # noqa: PLC0415

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=user.id,
            org_id=org.id,
            event_type=evt.MARKETPLACE_ACTIVATE,
            ip_address=None,
            metadata={"model_id": project.source_ref, "project_id": project.id},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    if (
        listing is not None
        and listing.author_organization_id
        and listing.author_organization_id != org.id
    ):
        try:
            from app.services.notification_service import NotificationService  # noqa: PLC0415

            author_users = (
                db.query(User)
                .filter(
                    User.organization_id == listing.author_organization_id,
                    User.is_active == True,  # noqa: E712
                )
                .all()
            )
            notification_svc = NotificationService(db)
            for author_user in author_users:
                notification_svc.send_author_notification(
                    user_id=author_user.id,
                    organization_id=listing.author_organization_id,
                    event_type="activation",
                    title="Model adopted",
                    message=(
                        f"Your model '{listing.display_name}' was added to another team's studio"
                    ),
                    # model_name travels in the payload so the interface can
                    # write this sentence in the reader's language; `message`
                    # above stays as the English fallback and the API value.
                    data={
                        "model_id": listing.model_project_id,
                        "model_name": listing.display_name,
                    },
                    link="/workspace/models",
                )
            db.commit()
        except Exception:
            logger.debug("Failed to send adoption notification", exc_info=True)

    return project


@router.post(
    "/{project_id}/publish",
    response_model=ModelCatalogResponse,
    operation_id="publish_model_project",
)
def publish_model_project(
    project_id: str,
    body: PublishModelRequest,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelCatalogResponse:
    """Publish a project to the marketplace (upsert its listing facet + pin HEAD version).

    P1.5 fusion: publishing attaches a ``ModelProjectListing`` to the project instead of
    copying the model into a separate catalog row. Requires a committed version (the
    listing pins HEAD, never the dirty draft).
    """
    project = _writable_project_or_404(db, project_id, org.id)
    try:
        listing = svc.publish_listing(db, project, author_org_id=org.id, req=body)
    except ProjectNotPublishableError as exc:
        # Additive: `detail` is the same English sentence API/MCP clients already
        # read; `code` is what lets the browser say WHICH of the two refusals it is.
        raise CodedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
            code=exc.code,
        ) from exc
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
    db.refresh(listing)
    response = listing_to_catalog_response(listing)
    response.author_name = org.name
    response.author_verified = org.is_verified
    return response


@router.post(
    "/{project_id}/unpublish",
    response_model=ModelCatalogResponse,
    operation_id="unpublish_model_project",
)
def unpublish_model_project(
    project_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelCatalogResponse:
    """Withdraw a published project from the marketplace, reversibly.

    The listing keeps its rollups (adoptions, executions, rating) so
    ``/republish`` restores it as it was. Forks already made keep working —
    adoption copies the model, it does not reference the listing.
    """
    return _set_publication(db, project_id, user=user, org=org, published=False)


@router.post(
    "/{project_id}/republish",
    response_model=ModelCatalogResponse,
    operation_id="republish_model_project",
)
def republish_model_project(
    project_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelCatalogResponse:
    """Put a withdrawn listing back on the marketplace, as it was.

    The pinned version is left untouched: republishing restores the listing, it
    does not re-pin HEAD. Use ``/publish`` to publish a newer version.
    """
    return _set_publication(db, project_id, user=user, org=org, published=True)


def _set_publication(
    db: Session,
    project_id: str,
    *,
    user: User,
    org: Organization,
    published: bool,
) -> ModelCatalogResponse:
    """Shared body of un/republish: both differ only in the target status."""
    project = _writable_project_or_404(db, project_id, org.id)
    try:
        listing = svc.set_listing_published(db, project, published=published)
    except svc.ListingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.ListingStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_PUBLISH if published else AuditAction.MODEL_UNPUBLISH,
        target_type="model_project",
        target_id=project.id,
        target_name=project.name,
    )
    db.commit()
    db.refresh(listing)
    response = listing_to_catalog_response(listing)
    # `org` is the CurrentOrg dependency — already loaded, so re-selecting it here
    # only costs a round trip.
    response.author_name = org.name
    response.author_verified = org.is_verified
    return response


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
) -> list[ProjectListItem]:
    """List the organization's ModelProjects (newest-updated first).

    The list is org-wide (collaborative); pass ``mine=true`` to narrow it to the
    current user's own models. Each row carries its marketplace publication
    state so the studio can show which models are published.
    """
    projects = svc.list_projects(
        db,
        org_id=org.id,
        status=status_filter,
        workspace_id=workspace_id,
        q=q,
        created_by=user.id if mine else None,
        skip=skip,
        limit=limit,
    )
    # One batch query for the listing facets — reading them per project would be N+1.
    listing_status: dict[str, str] = {}
    if projects:
        rows = (
            db.query(ModelProjectListing.model_project_id, ModelProjectListing.status)
            .filter(ModelProjectListing.model_project_id.in_([p.id for p in projects]))
            .all()
        )
        listing_status = {row.model_project_id: row.status for row in rows}

    items: list[ProjectListItem] = []
    for project in projects:
        item = ProjectListItem.model_validate(project)
        item.listing_status = listing_status.get(project.id)
        items.append(item)
    return items


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
    """Patch project metadata (name / description / status).

    This route is both the rename and the restore, so it cannot use
    ``_writable_project_or_404``: on an archived project only the restore may
    pass. Everything else — a rename, a new description, a re-archive — is
    refused with the same message as every other write.
    """
    project = _project_or_404(db, project_id, org.id)
    if project.status == "archived" and body.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ARCHIVED_DETAIL)
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
    project = _writable_project_or_404(db, project_id, org.id)
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
# Datasets — named data bundles / scenarios (§8)
# --------------------------------------------------------------------------- #
@router.get(
    "/{project_id}/datasets",
    response_model=list[DatasetSummary],
    operation_id="list_project_datasets",
)
def list_project_datasets(
    project_id: str, db: DBSession, org: CurrentOrg, _ws: OptionalRequireViewer
) -> list[ModelProjectDataset]:
    """List a project's datasets (values omitted — fetch one for its data_json)."""
    project = _project_or_404(db, project_id, org.id)
    return svc.list_datasets(db, project)


@router.post(
    "/{project_id}/datasets",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_project_dataset",
)
def create_project_dataset(
    project_id: str,
    body: DatasetCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelProjectDataset:
    """Create a named dataset ("scenario") for the project."""
    project = _writable_project_or_404(db, project_id, org.id)
    try:
        dataset = svc.create_dataset(
            db,
            project,
            user_id=user.id,
            name=body.name,
            description=body.description,
            data_json=body.data_json,
        )
    except JModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    except ProjectConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_EDIT,
        target_type="model_project_dataset",
        target_id=dataset.id,
        target_name=dataset.name,
    )
    db.commit()
    db.refresh(dataset)
    return dataset


@router.post(
    "/{project_id}/datasets/import",
    response_model=DatasetImportPreview,
    operation_id="import_project_dataset",
)
def import_project_dataset(  # sync ON PURPOSE -> threadpool (ADR-009): parses the file
    project_id: str,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
    file: UploadFile = File(...),
    param_name: str | None = Form(default=None, max_length=255),
) -> DatasetImportPreview:
    """Parse an uploaded ``.dat`` / ``.json`` / ``.csv`` file into a dataset PREVIEW (S2c).

    Nothing is stored: the response carries the parsed ``data_json`` (already run
    through the same validation as create, so the preview fails early with the
    compiler-grade message) + a name suggestion; the user saves through the normal
    create. ``param_name`` names the single CSV param (defaults from the filename).
    """
    from app.services import dataset_import_service  # noqa: PLC0415

    _project_or_404(db, project_id, org.id)
    # Read the already-spooled upload directly: Starlette buffers it before the
    # handler runs, and parsing up to 16 MB of dataset is CPU-bound work that has no
    # business on the event loop (ADR-009).
    content = file.file.read()
    if len(content) > svc.MAX_DATASET_JSON_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"file is too large ({len(content):,} bytes — max {svc.MAX_DATASET_JSON_BYTES:,})"
            ),
        )
    try:
        data_json, suggested_name = dataset_import_service.parse_dataset_file(
            file.filename or "dataset", content, param_name
        )
        svc.validate_dataset_json(data_json)
    except JModelError as exc:
        detail = exc.message
        if exc.position is not None:
            detail += f" (pos {exc.position})"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        ) from exc
    return DatasetImportPreview(data_json=data_json, suggested_name=suggested_name)


@router.get(
    "/{project_id}/datasets/{dataset_id}",
    response_model=DatasetRead,
    operation_id="get_project_dataset",
)
def get_project_dataset(
    project_id: str,
    dataset_id: str,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireViewer,
) -> ModelProjectDataset:
    """Fetch a dataset with its full values."""
    dataset = svc.get_dataset_or_404(db, dataset_id, org.id, project_id=project_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


@router.put(
    "/{project_id}/datasets/{dataset_id}",
    response_model=DatasetRead,
    operation_id="update_project_dataset",
)
def update_project_dataset(
    project_id: str,
    dataset_id: str,
    body: DatasetUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelProjectDataset:
    """Update a dataset's name/description/values (only the provided fields)."""
    _writable_project_or_404(db, project_id, org.id)
    dataset = svc.get_dataset_or_404(db, dataset_id, org.id, project_id=project_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        dataset = svc.update_dataset(
            db,
            dataset,
            name=body.name,
            description=body.description,
            data_json=body.data_json,
        )
    except JModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    except ProjectConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_EDIT,
        target_type="model_project_dataset",
        target_id=dataset.id,
        target_name=dataset.name,
    )
    db.commit()
    db.refresh(dataset)
    return dataset


@router.delete(
    "/{project_id}/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_project_dataset",
)
def delete_project_dataset(
    project_id: str,
    dataset_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> None:
    """Delete a dataset (working data — no archive tier)."""
    _writable_project_or_404(db, project_id, org.id)
    dataset = svc.get_dataset_or_404(db, dataset_id, org.id, project_id=project_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_DELETE,
        target_type="model_project_dataset",
        target_id=dataset.id,
        target_name=dataset.name,
    )
    svc.delete_dataset(db, dataset)
    db.commit()


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
    project = _writable_project_or_404(db, project_id, org.id)
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
    project = _writable_project_or_404(db, project_id, org.id)
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
# Solve (rides the single async pipeline — ADR-007 S4a)
# --------------------------------------------------------------------------- #
@router.post(
    "/{project_id}/solve",
    response_model=OptimizationResult,
    operation_id="solve_model_project",
    dependencies=[Depends(solve_maintenance_gate)],
)
def solve_model_project(  # def: blocks on the queued result in the threadpool (ADR-007 S4a)
    project_id: str,
    request: Request,
    db: DBSession,
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    version_id: str | None = Query(default=None),
    solver_name: str | None = Query(default=None, max_length=32),
    origin: str | None = Query(default=None, max_length=32),
    solution_filter: Literal["nonzero"] | None = Query(
        default=None,
        description=(
            "Compact solution: 'nonzero' omits near-zero variables from the "
            "response (variables_omitted reports the count). The persisted "
            "execution keeps the full solution."
        ),
    ),
) -> Any:
    """Solve a ModelProject's draft (or a specific committed version).

    ADR-007 S4a — async-under-the-hood: resolves the project/version model
    server-side, then rides the ONE async pipeline (``enqueue_async_solve``)
    exactly like ``POST /solve`` — tier caps, auto-routing, the
    pending ModelExecution row (tagged ``model_project`` provenance + typed
    project/version columns), and the Celery worker. The classic
    ``OptimizationResult`` comes back on completion; a solve that outlives the
    wait budget returns 202 + the task envelope (poll or subscribe).

    ``origin`` lets a programmatic caller (API/MCP/ERP) label the run honestly;
    it is sanitized server-side and falls back to ``visual_builder`` (the studio),
    which is the historical default for this endpoint.
    """
    org = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    project = _writable_project_or_404(db, project_id, org.id)

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

    enforce_org_rate_limit(db, org)

    try:
        problem = OptimizationProblem.model_validate(model_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation_summary(
                exc, prefix="Stored model is not a valid optimization problem."
            ),
        ) from exc

    # Tier caps, auto-routing, credit pre-pay, provenance, and the pending row all
    # happen inside the ONE enqueue path — the typed model_project_id resolves from
    # source_id ownership (project is in-org above), and mpv_id rides alongside it.
    enqueued = enqueue_async_solve(
        db=db,
        org=org,
        user=getattr(request.state, "user", None),
        problem=problem,
        workspace_id=workspace_member.workspace_id if workspace_member else None,
        solver_name_param=solver_name,
        origin=origin or ORIGIN_VISUAL_BUILDER,
        source_kind="model_project",
        source_id=project.id,
        dataset_id=None,
        model_project_version_id=mpv_id,
        parser=solver.parser,
    )
    payload = wait_for_task(enqueued.task)
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
    return apply_solution_filter(
        shape_sync_result(
            payload,
            db=db,
            org_id=org.id,
            execution_id=enqueued.execution_id,
            solver_used=enqueued.effective_solver,
            auto_route_reason=enqueued.auto_route_reason,
            fallback_triggered=enqueued.fallback_triggered,
        ),
        solution_filter,
    )


@router.post(
    "/{project_id}/datasets/{dataset_id}/solve",
    response_model=AsyncSolveEnvelope,
    operation_id="solve_project_dataset",
    dependencies=[Depends(solve_maintenance_gate)],
)
def solve_project_dataset(  # def: the CPU-bound compile belongs in the threadpool
    project_id: str,
    dataset_id: str,
    request: Request,
    db: DBSession,
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
) -> dict[str, Any]:
    """Solve one named dataset against the project's JModel source — SERVER-side.

    ADR-007 S7: the scenario launch used to compile in the BROWSER and upload the
    flat problem (~31MB each way for the large TFM scenarios) through the Next
    proxy; this endpoint compiles the persisted ``draft_dsl_source`` + dataset on
    the server and rides the ONE async pipeline, so the client sends a URL and
    nothing else. Async-only on purpose — scenario launches are batch and the
    client derives row state from the server. A compile failure is a 422
    ``{message, position}``; the dataset is
    org- and project-scoped (404 otherwise, anti-oracle).
    """
    org = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    project = _writable_project_or_404(db, project_id, org.id)
    source = project.draft_dsl_source
    if not source or not source.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This project has no JModel source — scenarios recompile the "
                "JModel source against each dataset."
            ),
        )

    dataset = svc.get_dataset_or_404(db, dataset_id, org.id, project_id=project_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    enforce_org_rate_limit(db, org)

    try:
        problem = compile_jmodel(source, data=JModelData.from_json(dataset.data_json))
    except JModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "position": exc.position},
        ) from exc

    # Same enqueue path and provenance the browser-side launch produced (origin
    # visual_builder + model_project source + S1 dataset snapshot), so history
    # rows are indistinguishable from pre-S7 scenario runs.
    enqueued = enqueue_async_solve(
        db=db,
        org=org,
        user=getattr(request.state, "user", None),
        problem=problem,
        workspace_id=workspace_member.workspace_id if workspace_member else None,
        solver_name_param=solver_name,
        origin=ORIGIN_VISUAL_BUILDER,
        source_kind="model_project",
        source_id=project.id,
        dataset_id=dataset.id,
        parser=solver.parser,
    )
    return enqueued.envelope
