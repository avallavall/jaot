"""Pure planning logic for the solver comparer.

Nothing here touches a database or a solver. These are the decisions the
comparison makes before anything runs: what terms every column gets, which
columns can run at all, and whether the finished columns tell the same story.
"""

from __future__ import annotations

import pytest

from app.domains.solver.services.comparison_service import (
    REASON_NOT_AVAILABLE,
    REASON_NOT_REGISTERED,
    Agreement,
    SolvedColumn,
    build_comparison_problem,
    compute_agreement,
    normalize_solver_names,
    plan_comparison,
)
from app.schemas.optimization import OptimizationProblem

pytestmark = pytest.mark.unit

_PROBLEM = OptimizationProblem.model_validate(
    {
        "name": "tiny",
        "variables": [
            {"name": "x", "type": "continuous", "lower_bound": 0},
            {"name": "y", "type": "continuous", "lower_bound": 0},
        ],
        "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
        "constraints": [{"name": "cap", "expression": "x + y <= 10"}],
    }
)


class TestNormalizeSolverNames:
    def test_lowercases_strips_and_deduplicates_keeping_order(self) -> None:
        assert normalize_solver_names([" HiGHS ", "scip", "highs", "SCIP"]) == ["highs", "scip"]

    def test_blank_entries_are_dropped(self) -> None:
        assert normalize_solver_names(["", "   ", "scip"]) == ["scip"]


class TestBuildComparisonProblem:
    def test_the_settings_are_stamped_onto_a_copy(self) -> None:
        result = build_comparison_problem(
            _PROBLEM, time_limit_seconds=7, gap_tolerance=0.05, threads=3
        )

        assert result.options.time_limit_seconds == 7
        assert result.options.gap_tolerance == 0.05
        assert result.options.threads == 3
        # The caller's problem is untouched (project immutability rule).
        assert _PROBLEM.options.time_limit_seconds != 7

    def test_verbose_is_forced_off(self) -> None:
        noisy = _PROBLEM.model_copy(
            update={"options": _PROBLEM.options.model_copy(update={"verbose": True})}
        )
        result = build_comparison_problem(
            noisy, time_limit_seconds=10, gap_tolerance=0.001, threads=1
        )
        assert result.options.verbose is False

    def test_a_problem_naming_its_own_solver_has_it_cleared(self) -> None:
        pinned = _PROBLEM.model_copy(update={"solver_name": "scip"})
        result = build_comparison_problem(
            pinned, time_limit_seconds=10, gap_tolerance=0.001, threads=1
        )
        # Otherwise every column of the comparison would run the same solver.
        assert result.solver_name is None


class TestPlanComparison:
    def test_a_registered_capable_solver_will_run(self) -> None:
        plan = {entry.solver_name: entry for entry in plan_comparison(_PROBLEM, ["scip"])}
        assert plan["scip"].will_run is True
        assert plan["scip"].unsupported_reason is None

    def test_an_unknown_solver_is_reported_not_registered(self) -> None:
        plan = {entry.solver_name: entry for entry in plan_comparison(_PROBLEM, ["nope"])}
        assert plan["nope"].will_run is False
        assert plan["nope"].unsupported_reason == REASON_NOT_REGISTERED

    def test_hexaly_can_never_take_part(self) -> None:
        # Its SDK and licence live only on the Hexaly worker image; the
        # comparison worker runs the base image so one machine times everything.
        plan = {entry.solver_name: entry for entry in plan_comparison(_PROBLEM, ["hexaly"])}
        assert plan["hexaly"].unsupported_reason == REASON_NOT_AVAILABLE

    def test_the_plan_keeps_the_requested_order(self) -> None:
        names = [entry.solver_name for entry in plan_comparison(_PROBLEM, ["highs", "scip"])]
        assert names == ["highs", "scip"]


class TestComputeAgreement:
    def test_one_column_cannot_agree_or_disagree(self) -> None:
        result = compute_agreement([SolvedColumn("scip", 24.0, {"x": 4.0})])
        assert result.objectives_agree is None
        assert result.solutions_identical is None

    def test_identical_results_agree(self) -> None:
        result = compute_agreement(
            [
                SolvedColumn("scip", 24.0, {"x": 4.0, "y": 6.0}),
                SolvedColumn("highs", 24.0, {"x": 4.0, "y": 6.0}),
            ]
        )
        assert result.objectives_agree is True
        assert result.solutions_identical is True
        assert result.alternative_optima is False

    def test_same_objective_with_different_variables_is_alternative_optima(self) -> None:
        # Both solvers are right. The problem simply has more than one optimal
        # solution, and saying so is the difference between a useful table and
        # one that looks like a bug.
        result = compute_agreement(
            [
                SolvedColumn("scip", 24.0, {"x": 4.0, "y": 6.0}),
                SolvedColumn("highs", 24.0, {"x": 0.0, "y": 10.0}),
            ]
        )
        assert result.objectives_agree is True
        assert result.solutions_identical is False
        assert result.alternative_optima is True

    def test_different_objectives_do_not_agree(self) -> None:
        result = compute_agreement(
            [
                SolvedColumn("scip", 24.0, {"x": 4.0}),
                SolvedColumn("highs", 19.5, {"x": 4.0}),
            ]
        )
        assert result.objectives_agree is False
        assert result.max_objective_delta == pytest.approx(4.5)
        # Not alternative optima: they disagree about the value itself.
        assert result.alternative_optima is False

    def test_tolerance_is_relative_to_the_magnitude(self) -> None:
        # Floating-point noise on a large objective must not read as a
        # disagreement; an absolute epsilon would call this a mismatch.
        big = 1_000_000.0
        result = compute_agreement(
            [SolvedColumn("scip", big, None), SolvedColumn("highs", big + 0.4, None)]
        )
        assert result.objectives_agree is True

    def test_a_missing_variable_makes_the_solutions_differ(self) -> None:
        result = compute_agreement(
            [
                SolvedColumn("scip", 1.0, {"x": 1.0, "y": 0.0}),
                SolvedColumn("highs", 1.0, {"x": 1.0}),
            ]
        )
        assert result.solutions_identical is False

    def test_the_result_is_a_plain_agreement(self) -> None:
        assert isinstance(compute_agreement([]), Agreement)
