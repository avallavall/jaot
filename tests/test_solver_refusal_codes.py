"""A solver's refusal of a quadratic model reaches the page as a code.

# CONTRACT-TEST: a linear-only refusal carries ``error_code`` + ``error_params`` on the result
# and on the stored execution, and every such code has words in frontend/messages/en.json.

JAOS, HiGHS, CBC and GLPK solve linear models only and refuse a quadratic one.
The refusal travelled as one English ``error_message``, and the execution page
printed it in every locale (QA, 2026-09-25, "JAOS in JAOT takes linear models
only — quadratic term 'x*x' ..." on the Spanish page). The English text stays:
API clients read it, and it is the page's fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domains.solver.adapters.cbc import CBCAdapter
from app.domains.solver.adapters.glpk import GLPKAdapter
from app.domains.solver.adapters.highs import HiGHSAdapter
from app.domains.solver.adapters.jaos import JAOSAdapter
from app.models import ModelExecution
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
    Variable,
)

_MESSAGES = Path(__file__).resolve().parent.parent / "frontend" / "messages" / "en.json"


def _problem(objective: str, constraint: str) -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="x", lower_bound=0, upper_bound=3),
            Variable(name="y", lower_bound=0, upper_bound=3),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression=objective),
        constraints=[Constraint(name="budget", expression=constraint)],
    )


@pytest.mark.parametrize(("adapter", "label"), [(JAOSAdapter, "JAOS"), (HiGHSAdapter, "HiGHS")])
def test_a_quadratic_objective_is_refused_with_a_code(adapter, label):
    result = adapter().solve(_problem("x*x + y", "x + y <= 4"))

    assert result.status is SolverStatus.ERROR
    assert result.error_code == "solver.quadratic_in_objective"
    assert result.error_params == {"solver": label, "term": "x*x"}
    # The English sentence is still there for API clients and as the fallback.
    assert "linear" in (result.error_message or "")


@pytest.mark.parametrize(("adapter", "label"), [(JAOSAdapter, "JAOS"), (HiGHSAdapter, "HiGHS")])
def test_a_quadratic_constraint_is_refused_with_a_code(adapter, label):
    result = adapter().solve(_problem("x + y", "x*y <= 4"))

    assert result.status is SolverStatus.ERROR
    assert result.error_code == "solver.quadratic_in_constraint"
    assert result.error_params == {"solver": label, "term": "x*y", "constraint": "budget"}


@pytest.mark.parametrize(("adapter", "label"), [(CBCAdapter, "CBC"), (GLPKAdapter, "GLPK")])
def test_a_command_line_solver_refuses_with_a_code(adapter, label):
    result = adapter().solve(_problem("x + y", "x*y <= 4"))

    assert result.status is SolverStatus.ERROR
    assert result.error_code == "solver.linear_only"
    assert result.error_params == {"solver": label}
    assert "quadratic" in (result.error_message or "").lower()


def test_any_other_error_carries_no_code():
    """A code promises a known sentence. An unexpected failure has none."""
    result = HiGHSAdapter().solve(_problem("x", "x <> 4"))
    assert result.status is SolverStatus.ERROR
    assert result.error_code is None
    assert result.error_params is None


def test_the_stored_result_keeps_the_code():
    result = OptimizationResult(
        status=SolverStatus.ERROR,
        solve_time_seconds=0.0,
        error_message="HiGHS supports linear problems only",
        error_code="solver.linear_only",
        error_params={"solver": "HiGHS"},
    )
    stored = result.to_result_data()
    assert stored["error_code"] == "solver.linear_only"
    assert stored["error_params"] == {"solver": "HiGHS"}


def test_every_refusal_code_has_words_in_english():
    from app.domains.solver.adapters.base import LINEAR_ONLY_CODES

    codes = json.loads(_MESSAGES.read_text(encoding="utf-8"))["errors"]["codes"]
    missing = []
    for code in LINEAR_ONLY_CODES:
        node = codes
        for part in code.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, str) or not node.strip():
            missing.append(code)
    assert missing == [], f"refusal codes with no errors.codes entry in en.json: {missing}"


def test_a_refused_solve_stores_the_code_on_its_execution(authenticated_client, db_session):
    """Through the route and the worker, to the row the execution page reads."""
    problem = _problem("x*x + y", "x + y <= 4").model_dump(mode="json")
    problem["solver_name"] = "jaos"

    response = authenticated_client.post("/api/v2/solve", json=problem)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "error"
    assert body["error_code"] == "solver.quadratic_in_objective"

    db_session.expire_all()
    execution = db_session.get(ModelExecution, body["execution_id"])
    assert execution.status == "failed"
    assert execution.result_data is not None, "the failed run kept no result to read a code from"
    assert execution.result_data["error_code"] == "solver.quadratic_in_objective"
    assert execution.result_data["error_params"] == {"solver": "JAOS", "term": "x*x"}

    shown = authenticated_client.get(f"/api/v2/models/executions/{execution.id}")
    assert shown.json()["result_data"]["error_code"] == "solver.quadratic_in_objective"
