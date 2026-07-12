"""Template-based solve endpoints.

Extracted from app/api/v2/solve.py to reduce file size and improve
maintainability. These endpoints allow users to:

- List available optimization templates
- Get a specific template with full details
- Solve a problem using a template
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import OptionalRequireSolver
from app.api.v2.solve import _enqueue_async_solve, _shape_sync_result, _wait_for_task
from app.data.templates import load_all_templates
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.template_engine import TemplateEngine, get_template_engine
from app.models import Organization
from app.schemas.optimization import OptimizationProblem
from app.services.solve_orchestrator import ORIGIN_TEMPLATE
from app.services.template_resolver import (
    catalog_model_to_dict as _catalog_model_to_dict,
    resolve_template as _resolve_template,
)
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# Template resolution (id → engine-ready dict) lives in
# ``app/services/template_resolver.py`` so the ModelProject "create from template /
# marketplace" endpoints (P2) share ONE resolution path. Imported above as
# ``_resolve_template`` / ``_yaml_template_to_dict`` / ``_catalog_model_to_dict``.


@router.get("/metadata", operation_id="get_solve_metadata")
async def get_solve_metadata() -> dict[str, Any]:
    """Return available categories and generator types for model creation.

    Includes ``category_generators`` mapping each category to the generator
    types that have templates defined for that category.
    """
    from app.data.templates import get_category_generator_map
    from app.domains.solver.services.generators import GENERATOR_REGISTRY
    from app.models.optimization_model import ModelCategory

    return {
        "categories": [c.value for c in ModelCategory],
        "generator_types": sorted(set(GENERATOR_REGISTRY.list_generators())),
        "category_generators": get_category_generator_map(),
    }


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


@router.get("/templates", operation_id="list_templates")
async def list_templates(
    category: str | None = None,
    featured: bool | None = None,
) -> dict[str, Any]:
    """List all available optimization templates from YAML definitions."""
    yaml_templates = load_all_templates()
    results: list[dict[str, Any]] = []

    for t in yaml_templates:
        if category and t.category != category:
            continue
        if featured is not None and t.is_featured != featured:
            continue
        results.append(t.model_dump(include=_SUMMARY_FIELDS))

    return {"templates": results, "total": len(results)}


@router.get("/templates/{template_id}", operation_id="get_template")
async def get_template(
    template_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific template with full details including input schema and example.

    Resolution order: YAML templates → DB ModelCatalog.
    """
    yaml_dict, model = _resolve_template(template_id, db)

    if yaml_dict:
        return yaml_dict

    if not model:
        raise HTTPException(status_code=404, detail="Template not found")

    return _catalog_model_to_dict(model)


@router.post(
    "/templates/{template_id}/preview",
    response_model=OptimizationProblem,
    operation_id="preview_template",
)
async def preview_template(
    template_id: str,
    user_input: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    template_engine: TemplateEngine = Depends(get_template_engine),
) -> OptimizationProblem:
    """Render a template with input data and return the OptimizationProblem without solving."""
    yaml_dict, model = _resolve_template(template_id, db)

    if yaml_dict:
        input_data = user_input or yaml_dict.get("example_input") or {}
        return template_engine.render(yaml_dict, input_data)

    if not model:
        raise HTTPException(status_code=404, detail="Template not found")

    tmpl_dict = _catalog_model_to_dict(model)
    input_data = user_input or model.example_input or {}
    return template_engine.render(tmpl_dict, input_data)


@router.post("/templates/{template_id}/solve", operation_id="solve_with_template")
def solve_with_template(  # def: blocks on the queued result in the threadpool (ADR-007 S4a)
    template_id: str,
    user_input: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
) -> Any:
    """Solve a problem using a template.

    ADR-007 S4a — async-under-the-hood: renders the template into an
    OptimizationProblem server-side, then rides the ONE async pipeline
    (``_enqueue_async_solve``) exactly like ``POST /solve`` — tier caps,
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
    yaml_dict, model = _resolve_template(template_id, db)

    template: dict[str, Any]
    if yaml_dict:
        template = yaml_dict
    elif model is not None:
        template = _catalog_model_to_dict(model)
    else:
        raise HTTPException(status_code=404, detail="Template not found")

    # Get auth context
    org: Organization | None = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Rate limit check
    allowed, rate_info = check_rate_limit(org.id, org.rate_limit_per_minute, org.rate_limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

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
    enqueued = _enqueue_async_solve(
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
            ip_address=request.client.host if request.client else None,
            metadata={"template_id": template_id},
        )
    except Exception:
        logger.debug("Failed to log TEMPLATE_USE analytics event", exc_info=True)


@router.get("/examples", operation_id="get_example_problems")
async def get_example_problems() -> dict[str, Any]:
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
