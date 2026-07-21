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


# --------------------------------------------------------------------------- #
# Sensitivity L1 — family-level KPIs
# --------------------------------------------------------------------------- #


def _family_problem() -> OptimizationProblem:
    """Two heuristic constraint families (cap_*, floor_*) over x_1/x_2/y_1."""
    return OptimizationProblem(
        variables=[
            Variable(name="x_1", type=VariableType.CONTINUOUS),
            Variable(name="x_2", type=VariableType.CONTINUOUS),
            Variable(name="y_1", type=VariableType.CONTINUOUS),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*x_1 + 2*x_2 + 5*y_1"),
        constraints=[
            Constraint(name="cap_1", expression="x_1 + y_1 <= 10"),
            Constraint(name="cap_2", expression="x_2 + y_1 <= 20"),
            Constraint(name="floor_1", expression="x_1 >= 1"),
            Constraint(name="floor_2", expression="x_2 >= 1"),
        ],
    )


def test_family_stats_aggregate_binding_slack_and_utilization():
    # x*: cap_1 binding (2+8=10), cap_2 slack 8 (4+8=12), floor_1 slack 1, floor_2 slack 3.
    a = compute_exact_analysis(_family_problem(), {"x_1": 2.0, "x_2": 4.0, "y_1": 8.0})

    by = {f.family: f for f in a.families}
    assert set(by) == {"cap", "floor"}
    cap = by["cap"]
    assert cap.total == 2 and cap.binding_count == 1
    assert cap.slack_min == pytest.approx(0.0)
    assert cap.slack_mean == pytest.approx(4.0)
    assert cap.slack_max == pytest.approx(8.0)
    assert cap.utilization_mean == pytest.approx((1.0 + 0.6) / 2)
    assert cap.utilization_max == pytest.approx(1.0)
    floor = by["floor"]
    assert floor.total == 2 and floor.binding_count == 0
    assert floor.slack_min == pytest.approx(1.0)
    assert floor.slack_max == pytest.approx(3.0)
    # >= rows have no utilization; the family reports None, not a bogus 0.
    assert floor.utilization_mean is None and floor.utilization_max is None
    # The saturated family (higher binding ratio) leads the ranking.
    assert [f.family for f in a.families] == ["cap", "floor"]


def test_family_stats_cover_rows_beyond_the_display_cap():
    # 250 one-family rows > _MAX_ROWS (200): the KPIs must still count all 250.
    problem = OptimizationProblem(
        variables=[Variable(name="x_1", type=VariableType.CONTINUOUS)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x_1"),
        constraints=[Constraint(name=f"cap_{i}", expression=f"x_1 <= {i + 1}") for i in range(250)],
    )
    a = compute_exact_analysis(problem, {"x_1": 1.0})
    assert len(a.constraints) == 200 and a.truncated_constraints
    (cap,) = a.families
    assert cap.total == 250
    assert cap.binding_count == 1  # only x_1 <= 1 is tight
    assert not a.truncated_families


def test_authoritative_family_suppresses_name_heuristic():
    # One compiler-annotated row ⇒ unannotated rows are deliberate scalars: the
    # "use_1" NAME must not be parsed into a phantom "use" family.
    problem = _problem([], "x + y")
    problem = problem.model_copy(
        update={
            "constraints": [
                Constraint(name="cap_s1", expression="x + y <= 10", family="cap"),
                Constraint(name="use_1", expression="x >= 0"),
            ]
        }
    )
    a = compute_exact_analysis(problem, {"x": 1.0, "y": 2.0})
    assert [f.family for f in a.families] == ["cap"]
    by_name = {c.name: c for c in a.constraints}
    assert by_name["cap_s1"].family == "cap"
    assert by_name["use_1"].family is None


def test_contribution_families_roll_up_by_variable_family():
    a = compute_exact_analysis(_family_problem(), {"x_1": 2.0, "x_2": 4.0, "y_1": 8.0})
    by = {f.family: f for f in a.contribution_families}
    assert by["x"].contribution == pytest.approx(3 * 2.0 + 2 * 4.0)
    assert by["x"].terms == 2
    assert by["y"].contribution == pytest.approx(5 * 8.0)
    # Sorted by |contribution| descending: y (40) before x (14).
    assert [f.family for f in a.contribution_families] == ["y", "x"]


def test_cross_family_bilinear_term_owned_by_no_family():
    problem = OptimizationProblem(
        variables=[
            Variable(name="x_1", type=VariableType.CONTINUOUS),
            Variable(name="y_1", type=VariableType.CONTINUOUS),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="2*x_1*y_1 + 3*x_1"),
        constraints=[Constraint(name="cap_1", expression="x_1 + y_1 <= 10")],
    )
    a = compute_exact_analysis(problem, {"x_1": 2.0, "y_1": 3.0})
    by = {f.family: f for f in a.contribution_families}
    # x owns only its pure term; the x·y cross term has no single honest owner.
    assert by["x"].contribution == pytest.approx(6.0)
    assert by["x"].terms == 1
    assert "y" not in by
    # ...but the per-term list still shows the bilinear term itself.
    assert any(c.label == "x_1 · y_1" for c in a.contributions)


def test_unstructured_names_yield_no_families():
    problem = _problem([("cap", "x + y <= 10"), ("floor", "x >= 2")], "3*x + 2*y")
    a = compute_exact_analysis(problem, {"x": 2.0, "y": 8.0})
    assert a.families == []
    assert a.contribution_families == []
