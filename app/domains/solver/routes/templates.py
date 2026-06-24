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
from sqlalchemy.orm import Session

from app.api.deps import OptionalRequireSolver
from app.api.v2.solve import _enforce_tier_caps, calculate_credits
from app.data.templates import TemplateDefinition, get_yaml_template, load_all_templates
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.services import SolverService, get_solver_service
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.services.template_engine import TemplateEngine, get_template_engine
from app.models import ModelCatalog, Organization
from app.schemas.optimization import OptimizationProblem
from app.services.solve_orchestrator import SolveOrchestrator, validate_problem
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _yaml_template_to_dict(tmpl: TemplateDefinition) -> dict[str, Any]:
    """Convert a YAML TemplateDefinition to a template dict for the engine."""
    return {**tmpl.model_dump(), "generator": tmpl.generator_type}


def _resolve_template(
    template_id: str,
    db: Session,
) -> tuple[dict[str, Any] | None, ModelCatalog | None]:
    """Return (template_dict, None) or (None, catalog_model).

    Resolution order: YAML templates → DB catalog.
    Both may be None when template_id matches nothing.
    """
    yaml_tmpl = get_yaml_template(template_id)
    if yaml_tmpl:
        return _yaml_template_to_dict(yaml_tmpl), None

    model = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.id.in_([template_id, f"official_{template_id}"]),
            ModelCatalog.status == "published",
        )
        .first()
    )
    if model:
        return None, model

    return None, None


def _catalog_model_to_dict(model: ModelCatalog) -> dict[str, Any]:
    """Convert a ModelCatalog row to a template dict for the engine."""
    return {
        "id": model.id,
        "name": model.name,
        "display_name": model.display_name,
        "description": model.description,
        "scenario_description": model.scenario_description,
        "category": model.category,
        "tags": model.tags or [],
        "generator": model.generator_type,
        "generator_type": model.generator_type,
        "input_schema": model.input_schema,
        "input_fields": model.input_fields,
        "example_input": model.example_input,
    }


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
async def solve_with_template(
    template_id: str,
    user_input: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    solver: SolverService = Depends(get_solver_service),
    workspace_member: OptionalRequireSolver = None,
    solver_name: str | None = Query(default=None, max_length=32),
) -> Any:
    """Solve a problem using a template.

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
            detail=f"Failed to process input: {str(e)}",
        ) from e

    # Resolve the solver (query param; templates carry no body solver field).
    # "auto" routes via the auto-router; otherwise the named solver (or default).
    # Mirrors /api/v2/solve so template solves can target HiGHS/Hexaly/etc.
    if solver_name == "auto":
        from app.domains.solver.services.auto_router import select_solver

        effective_solver_name, _auto_reason, _fallback = select_solver(problem, solver.parser)
    else:
        effective_solver_name = solver_name or DEFAULT_SOLVER_NAME

    # D-11 / WR-04: direct hexaly + worker down → 503 BEFORE credit debit.
    ensure_hexaly_worker_or_503(effective_solver_name)

    # PRC-01 / D-02: per-solver credit multiplier applied via the resolved solver.
    credits_needed = calculate_credits(problem, solver_name=effective_solver_name, db=db)

    # Quick balance pre-check (the orchestrator will do the atomic deduction)
    if org.credits_balance < credits_needed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(f"Insufficient credits. Need {credits_needed}, have {org.credits_balance}"),
        )

    # Validate & enforce tier caps

    _enforce_tier_caps(db, org, problem)
    validate_problem(problem)

    # Extract workspace_id
    ws_id = workspace_member.workspace_id if workspace_member else None

    user = getattr(request.state, "user", None)

    # Delegate to orchestrator (handles pre-pay, solve, refund, analytics)
    from app.domains.solver.services.pool import get_solver_pool

    orchestrator = SolveOrchestrator(db, solver, get_solver_pool())
    try:
        return await orchestrator.solve_with_template(
            problem=problem,
            template_id=template_id,
            org=org,
            user=user,
            request=request,
            credits_needed=credits_needed,
            workspace_id=ws_id,
            solver_name=effective_solver_name,
        )
    except (SolverNotFoundError, SolverUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


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
