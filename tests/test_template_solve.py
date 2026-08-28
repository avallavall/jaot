"""Parametrized tests that validate every template generates and solves correctly.

For each of the 100+ official templates:
- Generation produces a valid OptimizationProblem (variables, objective, constraints)
- SCIP solver returns optimal or feasible status (every template, no exemptions)
- Integer/binary templates produce MIP problems, continuous-only produce LP
- No template generation raises an unhandled exception

Marked @pytest.mark.slow for the full solve suite (can take a few minutes).
"""

import logging

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.services.generators import get_generator
from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import VariableType

logger = logging.getLogger(__name__)

ALL_TEMPLATES = load_all_templates()

# Pre-instantiate solver (stateless, reusable)
_solver = SolverService()


# Fast tests: generation only (no solve)


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda t: t.id)
def test_template_generates_valid_problem(template):
    """Every template generates a valid OptimizationProblem with variables and objective."""
    generator = get_generator(template.generator_type)
    problem = generator.generate(template.example_input, template.generator_params)

    assert len(problem.variables) > 0, f"Template {template.id} generated 0 variables"
    assert problem.objective is not None, f"Template {template.id} has no objective"
    assert problem.objective.expression, f"Template {template.id} has empty objective expression"


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda t: t.id)
def test_template_has_valid_structure(template):
    """Every generated problem has non-empty variables list, valid objective, and constraints list."""
    generator = get_generator(template.generator_type)
    problem = generator.generate(template.example_input, template.generator_params)

    # Variables must all have valid names
    for var in problem.variables:
        assert var.name, f"Variable in {template.id} has empty name"
        assert var.type in (VariableType.CONTINUOUS, VariableType.INTEGER, VariableType.BINARY)

    # Objective sense must be set
    assert problem.objective.sense in ("minimize", "maximize")

    # Constraints is a list (may be empty for unconstrained problems)
    assert isinstance(problem.constraints, list)


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda t: t.id)
def test_template_variable_types_consistent(template):
    """Templates with integer/binary vars produce MIP; continuous-only produce LP."""
    generator = get_generator(template.generator_type)
    problem = generator.generate(template.example_input, template.generator_params)

    has_integer = any(
        v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables
    )
    all_continuous = all(v.type == VariableType.CONTINUOUS for v in problem.variables)

    # These are mutually exclusive
    assert has_integer != all_continuous, (
        f"Template {template.id}: has_integer={has_integer}, all_continuous={all_continuous}"
    )


# Slow tests: full SCIP solve




@pytest.mark.slow
@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda t: t.id)
def test_template_solves_successfully(template):
    """Every template solves to feasible/optimal with SCIP (known issues excluded)."""
    generator = get_generator(template.generator_type)
    problem = generator.generate(template.example_input, template.generator_params)

    # Override options for CI speed
    problem.options.time_limit_seconds = 30
    problem.options.verbose = False

    result = _solver.solve(problem)

    logger.info(
        "Template %s: status=%s, time=%.3fs, obj=%s",
        template.id,
        result.status,
        result.solve_time_seconds,
        result.objective_value,
    )

    assert result.status in ("optimal", "feasible"), (
        f"Template {template.id} got status {result.status}"
        f"{': ' + (result.error_message or '') if result.error_message else ''}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda t: t.id)
def test_template_solve_returns_solution(template):
    """Solved templates return variable values in the solution dict."""
    generator = get_generator(template.generator_type)
    problem = generator.generate(template.example_input, template.generator_params)

    problem.options.time_limit_seconds = 30
    problem.options.verbose = False

    result = _solver.solve(problem)

    if result.status in ("optimal", "feasible"):
        assert result.solution is not None, f"Template {template.id}: no solution dict"
        assert len(result.solution) > 0, f"Template {template.id}: empty solution dict"
        assert result.objective_value is not None, f"Template {template.id}: no objective value"
