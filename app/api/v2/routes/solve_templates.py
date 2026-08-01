"""Template-based solve endpoints — list a template, read one, solve through it.

Mounted under ``/solve`` alongside the solver domain's own routes; the paths are
unchanged.

It sits in the API layer, not in ``app/domains/solver/``, because resolving a
template id is a JAOT question: the answer may be a YAML template or a published
marketplace listing, and it is recorded in the platform's analytics. A solver
packaged on its own has no marketplace to search. What it does own — rendering a
resolved template into a problem — stays in the domain as ``template_engine``
(D-16).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import DBSession, OptionalRequireSolver, enforce_org_rate_limit
from app.api.v2.solve_pipeline import enqueue_async_solve, shape_sync_result, wait_for_task
from app.data.templates import load_all_templates
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.template_engine import TemplateEngine, get_template_engine
from app.models import Organization
from app.schemas.optimization import OptimizationProblem, OptimizationResult
from app.schemas.template import (
    ExampleProblemsResponse,
    SolveMetadataResponse,
    TemplateDetailResponse,
    TemplateListResponse,
    TemplateSummaryResponse,
)
from app.services.template_resolver import resolve_template_dict as _resolve_template_dict
from app.shared.constants.execution_provenance import ORIGIN_TEMPLATE
from app.shared.utils.request_helpers import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter()


# Template resolution (id → engine-ready dict) lives in
# ``app/services/template_resolver.py`` so the ModelProject "create from template /
# marketplace" endpoints (P2) share ONE resolution path. Imported above as
# ``_resolve_template_dict`` (YAML template or published marketplace listing → dict).


@router.get("/metadata", response_model=SolveMetadataResponse, operation_id="get_solve_metadata")
def get_solve_metadata() -> SolveMetadataResponse:
    """Return available categories and generator types for model creation.

    Includes ``category_generators`` mapping each category to the generator
    types that have templates defined for that category.
    """
    from app.data.templates import get_category_generator_map
    from app.domains.solver.services.generators import GENERATOR_REGISTRY
    from app.models.optimization_model import ModelCategory

    return SolveMetadataResponse(
        categories=[c.value for c in ModelCategory],
        generator_types=sorted(set(GENERATOR_REGISTRY.list_generators())),
        category_generators=get_category_generator_map(),
    )


_SUMMARY_FIELDS = {
    "id",
    "name",
    "display_name",
    "short_description",
    "description",
    "category",
    "tags",
    "problem_type_tags",
    "generator_type",
    "is_featured",
    "estimated_variables",
    "estimated_constraints",
}


@router.get("/templates", response_model=TemplateListResponse, operation_id="list_templates")
def list_templates(
    category: str | None = None,
    featured: bool | None = None,
) -> TemplateListResponse:
    """List all available optimization templates from YAML definitions."""
    yaml_templates = load_all_templates()
    results: list[TemplateSummaryResponse] = []

    for t in yaml_templates:
        if category and t.category != category:
            continue
        if featured is not None and t.is_featured != featured:
            continue
        results.append(TemplateSummaryResponse(**t.model_dump(include=_SUMMARY_FIELDS)))

    return TemplateListResponse(templates=results, total=len(results))


@router.get(
    "/templates/{template_id}", response_model=TemplateDetailResponse, operation_id="get_template"
)
def get_template(
    template_id: str,
    db: DBSession,
) -> TemplateDetailResponse:
    """Get a specific template with full details including input schema and example.

    Resolution order: YAML templates → published marketplace listing.
    """
    tmpl_dict, _origin = _resolve_template_dict(template_id, db)

    if tmpl_dict is None:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateDetailResponse(**tmpl_dict)


@router.post(
    "/templates/{template_id}/preview",
    response_model=OptimizationProblem,
    operation_id="preview_template",
)
def preview_template(
    template_id: str,
    db: DBSession,
    user_input: dict[str, Any] | None = None,
    template_engine: TemplateEngine = Depends(get_template_engine),
) -> OptimizationProblem:
    """Render a template with input data and return the OptimizationProblem without solving."""
    tmpl_dict, _origin = _resolve_template_dict(template_id, db)

    if tmpl_dict is None:
        raise HTTPException(status_code=404, detail="Template not found")

    input_data = user_input or tmpl_dict.get("example_input") or {}
    return template_engine.render(tmpl_dict, input_data)


@router.post(
    "/templates/{template_id}/solve",
    # The 202-degrade path returns a JSONResponse, which bypasses the response
    # model — so what this declares is exactly what the completed solve returns.
    response_model=OptimizationResult,
    operation_id="solve_with_template",
)
def solve_with_template(  # def: blocks on the queued result in the threadpool (ADR-007 S4a)
    template_id: str,
    user_input: dict[str, Any],
    request: Request,
    db: DBSession,
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
) -> Any:
    """Solve a problem using a template.

    ADR-007 S4a — async-under-the-hood: renders the template into an
    OptimizationProblem server-side, then rides the ONE async pipeline
    (``enqueue_async_solve``) exactly like ``POST /solve`` — tier caps,
    auto-routing, the pending
    ModelExecution row (tagged ``template`` provenance), and the Celery worker.
    The classic ``OptimizationResult`` comes back on completion; a solve that
    outlives the wait budget returns 202 + the task envelope (poll or subscribe).

    The template transforms user-friendly input into an optimization problem.
    Optional ``solver_name`` selects the solver (e.g. ``scip``, ``highs``,
    ``hexaly``) or ``auto`` to let the platform route; omit for the default.

    Example for knapsack template::

        {
            "capacity": 50,
            "items": [
                {"name": "laptop", "value": 600, "weight": 10},
                {"name": "camera", "value": 500, "weight": 5}
            ]
        }
    """
    template, _origin = _resolve_template_dict(template_id, db)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Get auth context
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Rate limit check
    enforce_org_rate_limit(db, org)

    # Transform input using template engine
    engine = get_template_engine()
    try:
        problem = engine.render(template, user_input)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process input: {e!s}",
        ) from e

    # Tier caps, "auto" routing, per-solver credit pricing (pre-pay), the pending
    # row, and Celery time limits all happen inside the ONE enqueue path.
    enqueued = enqueue_async_solve(
        db=db,
        org=org,
        user=getattr(request.state, "user", None),
        problem=problem,
        workspace_id=workspace_member.workspace_id if workspace_member else None,
        solver_name_param=solver_name,
        origin=ORIGIN_TEMPLATE,
        source_kind="template",
        source_id=template_id,
        dataset_id=None,
        parser=solver.parser,
    )
    # Template-specific analytics (the ONE thing the async pipeline doesn't carry):
    # fire the TEMPLATE_USE event so template-popularity analytics survive the
    # async migration. Fire-and-forget at submit time — a template was used
    # regardless of whether the solve completes inline or degrades to 202.
    _log_template_use(db, request, org, template_id)

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
    return shape_sync_result(
        payload,
        db=db,
        org_id=org.id,
        execution_id=enqueued.execution_id,
        solver_used=enqueued.effective_solver,
        auto_route_reason=enqueued.auto_route_reason,
        fallback_triggered=enqueued.fallback_triggered,
    )


def _log_template_use(
    db: Session,
    request: Request,
    org: Organization,
    template_id: str,
) -> None:
    """Fire-and-forget TEMPLATE_USE analytics (preserved from the old orchestrator
    path so template-popularity analytics survive the async-only migration)."""
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        user = getattr(request.state, "user", None)
        AnalyticsService(db).log_event(
            user_id=getattr(user, "id", "anonymous"),
            org_id=org.id,
            event_type=evt.TEMPLATE_USE,
            ip_address=get_client_ip(request),
            metadata={"template_id": template_id},
        )
    except Exception:
        logger.debug("Failed to log TEMPLATE_USE analytics event", exc_info=True)


@router.get(
    "/examples", response_model=ExampleProblemsResponse, operation_id="get_example_problems"
)
def get_example_problems() -> dict[str, Any]:
    """Get example optimization problems for testing."""
    return {
        "examples": [
            {
                "name": "simple_linear",
                "description": "Simple linear programming",
                "problem": {
                    "name": "simple_linear",
                    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
                    "variables": [
                        {"name": "x", "type": "continuous", "lower_bound": 0},
                        {"name": "y", "type": "continuous", "lower_bound": 0},
                    ],
                    "constraints": [
                        {"name": "c1", "expression": "x + y <= 4"},
                        {"name": "c2", "expression": "2*x + y <= 5"},
                    ],
                },
            },
            {
                "name": "production_planning",
                "description": "Integer programming",
                "problem": {
                    "name": "production_planning",
                    "objective": {"sense": "maximize", "expression": "50*widgets + 40*gadgets"},
                    "variables": [
                        {
                            "name": "widgets",
                            "type": "integer",
                            "lower_bound": 0,
                            "upper_bound": 100,
                        },
                        {"name": "gadgets", "type": "integer", "lower_bound": 0, "upper_bound": 80},
                    ],
                    "constraints": [
                        {"name": "machine", "expression": "2*widgets + 3*gadgets <= 240"},
                        {"name": "labor", "expression": "4*widgets + 2*gadgets <= 200"},
                        {"name": "materials", "expression": "widgets + gadgets <= 150"},
                    ],
                    "options": {"time_limit_seconds": 30},
                },
            },
            {
                "name": "knapsack",
                "description": "Binary knapsack problem",
                "problem": {
                    "name": "knapsack",
                    "objective": {
                        "sense": "maximize",
                        "expression": "60*item1 + 100*item2 + 120*item3 + 80*item4",
                    },
                    "variables": [{"name": f"item{i}", "type": "binary"} for i in range(1, 5)],
                    "constraints": [
                        {
                            "name": "weight",
                            "expression": "10*item1 + 20*item2 + 30*item3 + 15*item4 <= 50",
                        }
                    ],
                },
            },
            {
                "name": "diet_problem",
                "description": "Classic diet optimization",
                "problem": {
                    "name": "diet_problem",
                    "objective": {
                        "sense": "minimize",
                        "expression": "2*bread + 3*milk + 1.5*eggs + 4*meat",
                    },
                    "variables": [
                        {"name": n, "type": "continuous", "lower_bound": 0}
                        for n in ["bread", "milk", "eggs", "meat"]
                    ],
                    "constraints": [
                        {
                            "name": "cal",
                            "expression": "100*bread + 150*milk + 80*eggs + 250*meat >= 2000",
                        },
                        {
                            "name": "protein",
                            "expression": "4*bread + 8*milk + 6*eggs + 20*meat >= 50",
                        },
                        {
                            "name": "calcium",
                            "expression": "10*bread + 300*milk + 25*eggs + 10*meat >= 800",
                        },
                    ],
                },
            },
        ]
    }
