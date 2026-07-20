"""Exact, solution-based analysis (A3) — binding / slack / utilization + contributions."""

import pytest

from app.domains.solver.services.exact_analysis import compute_exact_analysis
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)

pytestmark = pytest.mark.unit


def _problem(constraints: list[tuple[str, str]], objective: str) -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS),
            Variable(name="y", type=VariableType.CONTINUOUS),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression=objective),
        constraints=[Constraint(name=n, expression=e) for n, e in constraints],
    )


def test_binding_and_slack_from_solution():
    problem = _problem(
        [("cap", "x + y <= 10"), ("floor", "x >= 2"), ("room", "x + y <= 20")],
        "3*x + 2*y",
    )
    a = compute_exact_analysis(problem, {"x": 2.0, "y": 8.0}, objective_value=22.0)

    by = {c.name: c for c in a.constraints}
    assert by["cap"].is_binding and abs(by["cap"].slack) < 1e-6
    assert by["cap"].activity == pytest.approx(10.0)
    assert by["cap"].utilization == pytest.approx(1.0)
    assert by["floor"].is_binding  # x == 2 exactly
    assert not by["room"].is_binding
    assert by["room"].slack == pytest.approx(10.0)
    assert by["room"].utilization == pytest.approx(0.5)
    assert a.binding_count == 2
    assert a.total_constraints == 3
    # binding constraints lead the list
    assert a.constraints[0].is_binding


def test_objective_contributions_sorted_by_magnitude():
    problem = _problem([("cap", "x + y <= 10")], "3*x + 2*y")
    a = compute_exact_analysis(problem, {"x": 2.0, "y": 8.0})
    labels = [c.label for c in a.contributions]
    values = [c.contribution for c in a.contributions]
    assert labels == ["y", "x"]  # 2*8=16 > 3*2=6
    assert values[0] == pytest.approx(16.0)
    assert values[1] == pytest.approx(6.0)


def test_duplicate_objective_terms_merge_into_one_contribution():
    # "2*x + 3*x" is ONE decision on x — two rows with the same label would collide
    # (the panel keys rows by label) and read as distinct drivers.
    problem = _problem([("cap", "x + y <= 10")], "2*x + 3*x + 2*y")
    a = compute_exact_analysis(problem, {"x": 1.0, "y": 2.0})
    labels = [c.label for c in a.contributions]
    assert labels.count("x") == 1
    by = {c.label: c.contribution for c in a.contributions}
    assert by["x"] == pytest.approx(5.0)
    assert by["y"] == pytest.approx(4.0)


def test_unparseable_constraint_is_skipped_not_fatal():
    problem = _problem([("ok", "x + y <= 10"), ("bad", "x + <= 10")], "x + y")
    a = compute_exact_analysis(problem, {"x": 1.0, "y": 1.0})
    names = {c.name for c in a.constraints}
    assert "ok" in names  # the good one survives; the malformed one is dropped
