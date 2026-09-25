"""Platform-wide execution monitoring for admins.

The admin panel's executions page used to call ``GET /models/executions/all``,
which filters by ``current_user.organization_id`` and is the organization's own
history. Under a heading that reads "Monitor all model executions across the
platform", an admin was shown one organization's runs and had no way to tell:
measured on the development database, 1,176 rows of 1,234, with 58 belonging to
three other organizations and simply absent.

This endpoint is the platform view that heading promised. It also answers the
two questions the page could not: how many executions exist, and how long they
really take on average — both computed in the database over everything the
filters select, not over the twenty rows a page happens to show.
"""

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, defer

from app.api.deps import DBSession
from app.models import Organization, SolverComparison, User
from app.models.model_project import ModelProject
from app.models.optimization_model import ModelExecution
from app.schemas.admin import AdminExecutionRow, AdminExecutionsResponse, AdminExecutionStats

router = APIRouter(tags=["admin-executions"])


def _project_of(e: ModelExecution) -> str | None:
    return (
        e.model_project_id
        or (e.source_id if e.source_kind == "model_project" else None)
        or e.organization_model_id
    )


def _model_names(
    db: Session, executions: list[ModelExecution]
) -> dict[str, tuple[str, str | None]]:
    """Resolve each run's model name, keyed by ``"{org_id}:{project_id}"``.

    The org-scoped list resolves names against one organization. Here the rows
    span organizations, so the key carries the organization too: ``source_id``
    is client-supplied on the solve request, and matching on the project id
    alone would let a run carrying another organization's id borrow that
    organization's model name.

    Only the four columns the row shows are read. Loading the whole project
    brought its working copy with it, which runs to megabytes per model.
    """
    pairs = {(e.organization_id, mp_id) for e in executions if (mp_id := _project_of(e))}
    if not pairs:
        return {}

    rows = (
        db.query(ModelProject.organization_id, ModelProject.id, ModelProject.name, User.name)
        .outerjoin(User, User.id == ModelProject.created_by)
        .filter(ModelProject.id.in_({mp_id for _, mp_id in pairs}))
        .all()
    )
    found = {(org, mp_id): (name, author) for org, mp_id, name, author in rows}
    return {
        f"{org}:{mp_id}": found[(org, mp_id)] for (org, mp_id) in pairs if (org, mp_id) in found
    }


def _problem_names(db: Session, executions: list[ModelExecution]) -> dict[str, str]:
    """The problem's own name for runs that have no saved model, by execution id.

    Most runs on the platform come from ``POST /solve``, the comparer or an
    import, and carry no project. The table showed "—" for every one of them,
    although the problem they solved has a name.

    A comparison column keeps no copy of the problem, so its parent names it.
    Any other run names its problem inside the stored input, and only that one
    field is read from it: the input holds the whole compiled problem.
    """
    names: dict[str, str] = {}
    comparisons = {e.comparison_id for e in executions if e.comparison_id}
    if comparisons:
        parents = dict(
            db.query(SolverComparison.id, SolverComparison.problem_name)
            .filter(SolverComparison.id.in_(comparisons))
            .all()
        )
        for e in executions:
            if e.comparison_id and parents.get(e.comparison_id):
                names[e.id] = parents[e.comparison_id]

    own = [e.id for e in executions if not e.comparison_id]
    if own:
        rows = (
            db.query(ModelExecution.id, ModelExecution.input_data["name"].as_string())
            .filter(ModelExecution.id.in_(own))
            .all()
        )
        names.update({eid: name for eid, name in rows if name})
    return {eid: name.strip()[:255] for eid, name in names.items() if name.strip()}


@router.get("/executions", response_model=AdminExecutionsResponse)
def list_platform_executions(
    db: DBSession,
    status: str | None = Query(None),
    origin: str | None = Query(None),
    organization_id: str | None = Query(None),
    solver: str | None = Query(None, max_length=32),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AdminExecutionsResponse:
    """Every execution on the platform, newest first, with its organization."""
    query = db.query(ModelExecution)
    if status:
        query = query.filter(ModelExecution.status == status)
    if origin:
        query = query.filter(ModelExecution.origin == origin)
    if organization_id:
        query = query.filter(ModelExecution.organization_id == organization_id)
    if solver:
        query = query.filter(ModelExecution.solver_name == solver)

    # The stats describe everything the filters select. Computing them from the
    # page is what made the panel report an average of 6.15 s when the real one
    # was 763 ms: twenty recent rows happened to include several 20-second
    # solves, and the figure sat in the header with nothing saying it was a
    # sample.
    stats_row = query.with_entities(
        func.count(ModelExecution.id),
        func.avg(ModelExecution.execution_time_ms),
    ).one()
    stats = AdminExecutionStats(
        total=int(stats_row[0] or 0),
        avg_execution_time_ms=float(stats_row[1]) if stats_row[1] is not None else None,
    )

    # The payloads hold the whole compiled problem, the whole solution and the
    # live progress trail. A table of twenty rows needs none of them, and loading them cost 37 MB per page
    # on the org-scoped list before it stopped doing so.
    page_query = query.order_by(ModelExecution.created_at.desc()).options(
        defer(ModelExecution.input_data),
        defer(ModelExecution.result_data),
        defer(ModelExecution.progress_data),
        defer(ModelExecution.scenario_analysis),
    )
    # The total is the count above. A second count through the shared paginator
    # wrapped the whole row, payload columns included, in its subquery.
    total = stats.total
    executions = page_query.offset((page - 1) * page_size).limit(page_size).all()

    org_names = dict(
        db.query(Organization.id, Organization.name)
        .filter(Organization.id.in_({e.organization_id for e in executions if e.organization_id}))
        .all()
    )
    names = _model_names(db, executions)
    # Only a run of no saved model is named by its problem. A run that points at
    # a project this organization does not own stays unnamed, as before.
    problem_names = _problem_names(db, [e for e in executions if not _project_of(e)])

    items = []
    for e in executions:
        name, author = names.get(f"{e.organization_id}:{_project_of(e)}", (None, None))
        name = name or problem_names.get(e.id)
        items.append(
            AdminExecutionRow(
                id=e.id,
                organization_id=e.organization_id,
                organization_name=org_names.get(e.organization_id),
                model_project_id=e.model_project_id,
                model_name=name,
                model_author=author,
                status=e.status,
                solver_name=e.solver_name,
                solver_status=e.solver_status,
                objective_value=e.objective_value,
                execution_time_ms=e.execution_time_ms,
                origin=e.origin,
                created_at=e.created_at,
                completed_at=e.completed_at,
            )
        )

    return AdminExecutionsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
        stats=stats,
    )
