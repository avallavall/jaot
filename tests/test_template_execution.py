"""Validate every catalog template's example_input generates and solves successfully.

This test ensures that NO template ships with a broken example. It runs
the full pipeline: load template → generate OptimizationProblem → solve.

If this test fails, a user clicking "Load Example" → "Run" will get an error.
"""

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.services.solver_service import SolverService
from app.domains.solver.services.template_engine import TemplateEngine

_templates = load_all_templates()
_engine = TemplateEngine()
_solver = SolverService()


def _template_ids() -> list[str]:
    return [t.id for t in _templates]


@pytest.mark.parametrize("template_id", _template_ids())
def test_template_example_executes_successfully(template_id: str) -> None:
    """Each template's example_input must produce a feasible/optimal solve."""
    tmpl = next(t for t in _templates if t.id == template_id)

    assert tmpl.example_input is not None, f"Template {template_id} has no example_input"

    tmpl_dict = tmpl.model_dump()
    # Map generator_type → generator (TemplateEngine expects 'generator' key)
    if "generator_type" in tmpl_dict and "generator" not in tmpl_dict:
        tmpl_dict["generator"] = tmpl_dict["generator_type"]

    example_dict = (
        tmpl.example_input.model_dump()
        if hasattr(tmpl.example_input, "model_dump")
        else dict(tmpl.example_input)
        if not isinstance(tmpl.example_input, dict)
        else tmpl.example_input
    )

    # Generate the optimization problem
    problem = _engine.render(tmpl_dict, example_dict)

    # Solve it
    result = _solver.solve(problem)

    status_str = str(result.status).lower()
    assert "optimal" in status_str or "feasible" in status_str, (
        f"Template {template_id} example_input did not solve successfully. "
        f"Status: {result.status}, Error: {getattr(result, 'error_message', None)}"
    )
