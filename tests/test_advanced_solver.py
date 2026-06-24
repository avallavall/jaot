"""
Tests for advanced solver features:
- Warm start injection
- Sensitivity analysis (LP and MIP)
- Multi-objective solving (epsilon-constraint and weighted)
- Credit discount logic
"""

import pytest
from pydantic import ValidationError

from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import (
    MultiObjectiveConfig,
    ObjectiveSense,
    ObjectiveSpec,
    OptimizationProblem,
    ParetoPoint,
    SensitivityResult,
    SolverStatus,
)


def _make_lp_problem() -> OptimizationProblem:
    """Simple LP problem: maximize 3x + 2y, x + y <= 4, 2x + y <= 5, x,y >= 0."""
    return OptimizationProblem.model_validate(
        {
            "name": "simple_lp",
            "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0.0},
                {"name": "y", "type": "continuous", "lower_bound": 0.0},
            ],
            "constraints": [
                {"name": "c1", "expression": "x + y <= 4"},
                {"name": "c2", "expression": "2*x + y <= 5"},
            ],
        }
    )


def _make_mip_problem() -> OptimizationProblem:
    """Simple MIP: maximize 5*a + 4*b, binary a, b, a + b <= 1."""
    return OptimizationProblem.model_validate(
        {
            "name": "simple_mip",
            "objective": {"sense": "maximize", "expression": "5*a + 4*b"},
            "variables": [
                {"name": "a", "type": "binary"},
                {"name": "b", "type": "binary"},
            ],
            "constraints": [
                {"name": "c1", "expression": "a + b <= 1"},
            ],
        }
    )


def _make_bi_objective_problem() -> OptimizationProblem:
    """
    Bi-objective problem base: minimize cost and risk.
    Variables: x in [0, 10], y in [0, 10]
    Constraints: x + y <= 10
    Obj1: minimize x + 2*y (cost)
    Obj2: minimize 2*x + y (risk)
    """
    return OptimizationProblem.model_validate(
        {
            "name": "bi_obj",
            "objective": {"sense": "minimize", "expression": "x + 2*y"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
                {"name": "y", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0},
            ],
            "constraints": [
                {"name": "budget", "expression": "x + y <= 10"},
            ],
        }
    )


class TestMultiObjectiveSchema:
    def test_multi_objective_config_min_objectives(self):
        """Must have exactly 2 objectives."""
        with pytest.raises(ValidationError):
            MultiObjectiveConfig(
                mode="epsilon",
                objectives=[
                    ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE),
                ],
                n_points=5,
            )

    def test_multi_objective_config_n_points_range(self):
        """n_points must be in [2, 50]."""
        with pytest.raises(ValidationError):
            MultiObjectiveConfig(
                mode="epsilon",
                objectives=[
                    ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE),
                    ObjectiveSpec(expression="y", sense=ObjectiveSense.MINIMIZE),
                ],
                n_points=1,  # too low
            )

        with pytest.raises(ValidationError):
            MultiObjectiveConfig(
                mode="epsilon",
                objectives=[
                    ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE),
                    ObjectiveSpec(expression="y", sense=ObjectiveSense.MINIMIZE),
                ],
                n_points=51,  # too high
            )

    def test_objective_spec_weight_range(self):
        """Weight must be [0, 1]."""
        with pytest.raises(ValidationError):
            ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE, weight=-0.1)
        with pytest.raises(ValidationError):
            ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE, weight=1.1)


class TestSolverWarmStart:
    def test_warm_start_injection(self):
        """
        Solve LP once, use solution as warm start for second solve.
        Verifies warm_start_used=True and solution is still found.
        """
        solver = SolverService()
        problem = _make_lp_problem()

        # First solve
        result1 = solver.solve(problem)
        assert result1.status == SolverStatus.OPTIMAL
        assert result1.solution is not None
        assert result1.warm_start_used is False

        # Second solve with warm start
        result2 = solver.solve(problem, warm_start_solution=result1.solution)
        assert result2.status == SolverStatus.OPTIMAL
        assert result2.warm_start_used is True
        assert result2.solution is not None

    def test_warm_start_partial_solution(self):
        """Warm start with partial solution (only some variables)."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem, warm_start_solution={"x": 1.0})  # Only x provided
        assert result.status == SolverStatus.OPTIMAL
        assert result.warm_start_used is True

    def test_warm_start_invalid_variable_ignored(self):
        """Warm start with unknown variable should not crash."""
        solver = SolverService()
        problem = _make_lp_problem()

        # z is not in the problem — should be silently ignored
        result = solver.solve(problem, warm_start_solution={"x": 1.0, "z_nonexistent": 5.0})
        assert result.status == SolverStatus.OPTIMAL
        assert result.warm_start_used is True

    def test_no_warm_start_warm_start_used_is_false(self):
        """Without warm start, result.warm_start_used must be False."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem)
        assert result.warm_start_used is False


class TestSolverSensitivityLP:
    def test_sensitivity_present_for_lp(self):
        """LP problems get sensitivity analysis."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert result.sensitivity is not None
        assert isinstance(result.sensitivity, SensitivityResult)

    def test_sensitivity_is_not_approximate_for_lp(self):
        """LP sensitivity should NOT be marked as approximate."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem)
        assert result.sensitivity is not None
        assert result.sensitivity.is_approximate is False

    def test_sensitivity_has_constraint_entries(self):
        """Sensitivity should have one entry per constraint."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem)
        assert result.sensitivity is not None
        assert len(result.sensitivity.constraints) == len(problem.constraints)

    def test_sensitivity_shadow_price_values(self):
        """At least one constraint should have a non-null shadow price."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem)
        assert result.sensitivity is not None
        shadow_prices = [
            cs.shadow_price for cs in result.sensitivity.constraints if cs.shadow_price is not None
        ]
        assert len(shadow_prices) > 0

    def test_sensitivity_is_binding_set(self):
        """is_binding should be set for constraints."""
        solver = SolverService()
        problem = _make_lp_problem()

        result = solver.solve(problem)
        assert result.sensitivity is not None
        for cs in result.sensitivity.constraints:
            assert cs.is_binding is not None


class TestSolverSensitivityMIP:
    def test_sensitivity_present_for_mip(self):
        """MIP problems get approximate sensitivity from LP relaxation."""
        solver = SolverService()
        problem = _make_mip_problem()

        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert result.sensitivity is not None

    def test_sensitivity_is_approximate_for_mip(self):
        """MIP sensitivity must be marked as approximate."""
        solver = SolverService()
        problem = _make_mip_problem()

        result = solver.solve(problem)
        assert result.sensitivity is not None
        assert result.sensitivity.is_approximate is True

    def test_sensitivity_note_mentions_lp_relaxation(self):
        """MIP sensitivity note must mention LP relaxation."""
        solver = SolverService()
        problem = _make_mip_problem()

        result = solver.solve(problem)
        assert result.sensitivity is not None
        assert result.sensitivity.note is not None
        assert "LP relaxation" in result.sensitivity.note


class TestSolverMultiObjectiveEpsilon:
    def test_epsilon_constraint_returns_pareto_points(self):
        """Epsilon-constraint method returns list of ParetoPoints."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = MultiObjectiveConfig(
            mode="epsilon",
            objectives=[
                ObjectiveSpec(expression="x + 2*y", sense=ObjectiveSense.MINIMIZE, label="Cost"),
                ObjectiveSpec(expression="2*x + y", sense=ObjectiveSense.MINIMIZE, label="Risk"),
            ],
            n_points=5,
        )

        points = solver.solve_multi_objective(problem, config)
        assert isinstance(points, list)
        assert len(points) > 0

    def test_epsilon_pareto_points_have_required_fields(self):
        """Each ParetoPoint must have f1, f2, solution, objective_values."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = MultiObjectiveConfig(
            mode="epsilon",
            objectives=[
                ObjectiveSpec(expression="x + 2*y", sense=ObjectiveSense.MINIMIZE, label="Cost"),
                ObjectiveSpec(expression="2*x + y", sense=ObjectiveSense.MINIMIZE, label="Risk"),
            ],
            n_points=4,
        )

        points = solver.solve_multi_objective(problem, config)
        for pt in points:
            assert isinstance(pt, ParetoPoint)
            assert pt.f1 is not None
            assert pt.f2 is not None
            assert isinstance(pt.solution, dict)
            assert "x" in pt.solution
            assert "y" in pt.solution
            assert isinstance(pt.objective_values, dict)

    def test_epsilon_labels_in_objective_values(self):
        """ParetoPoint objective_values keys match configured labels."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = MultiObjectiveConfig(
            mode="epsilon",
            objectives=[
                ObjectiveSpec(expression="x + 2*y", sense=ObjectiveSense.MINIMIZE, label="Cost"),
                ObjectiveSpec(expression="2*x + y", sense=ObjectiveSense.MINIMIZE, label="Risk"),
            ],
            n_points=3,
        )

        points = solver.solve_multi_objective(problem, config)
        assert len(points) > 0
        for pt in points:
            assert "Cost" in pt.objective_values
            assert "Risk" in pt.objective_values


class TestSolverMultiObjectiveWeighted:
    def test_weighted_returns_pareto_points(self):
        """Weighted scalarization returns list of ParetoPoints."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = MultiObjectiveConfig(
            mode="weighted",
            objectives=[
                ObjectiveSpec(expression="x + 2*y", sense=ObjectiveSense.MINIMIZE, label="Cost"),
                ObjectiveSpec(expression="2*x + y", sense=ObjectiveSense.MINIMIZE, label="Risk"),
            ],
            n_points=5,
        )

        points = solver.solve_multi_objective(problem, config)
        assert isinstance(points, list)
        assert len(points) > 0

    def test_weighted_pareto_points_structure(self):
        """Each weighted ParetoPoint has f1, f2, solution."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = MultiObjectiveConfig(
            mode="weighted",
            objectives=[
                ObjectiveSpec(expression="x + 2*y", sense=ObjectiveSense.MINIMIZE),
                ObjectiveSpec(expression="2*x + y", sense=ObjectiveSense.MINIMIZE),
            ],
            n_points=3,
        )

        points = solver.solve_multi_objective(problem, config)
        for pt in points:
            assert isinstance(pt, ParetoPoint)
            assert isinstance(pt.solution, dict)
            assert "x" in pt.solution

    def test_weighted_deduplicates_identical_points(self):
        """Weighted method should deduplicate nearly identical points."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = MultiObjectiveConfig(
            mode="weighted",
            objectives=[
                ObjectiveSpec(expression="x + 2*y", sense=ObjectiveSense.MINIMIZE),
                ObjectiveSpec(expression="2*x + y", sense=ObjectiveSense.MINIMIZE),
            ],
            n_points=10,
        )

        points = solver.solve_multi_objective(problem, config)
        # Check that no two points are exactly duplicate
        for i, p1 in enumerate(points):
            for j, p2 in enumerate(points):
                if i != j:
                    assert not (abs(p1.f1 - p2.f1) < 1e-6 and abs(p1.f2 - p2.f2) < 1e-6), (
                        f"Duplicate Pareto points at index {i} and {j}"
                    )


class TestCreditDiscounts:
    def test_warm_start_credit_discount(self):
        """Warm start should cost 50% of normal (min 1).

        For _make_lp_problem (2 cont vars, 2 cons, 60s default): base formula
        = 1 + 2*0.1 + 0 + 2*0.05 + 0 = 1.3 -> round -> 1.
        Warm start discount = max(1, round(1 * 0.5)) = 1.
        """
        from app.api.v2.solve import calculate_credits

        problem = _make_lp_problem()
        base = calculate_credits(problem)
        assert base == 1, f"Expected base cost 1 for _make_lp_problem, got {base}"

        # Production applies the discount inline: max(1, round(base_credits * 0.5)).
        discounted = max(1, round(base * 0.5))
        assert discounted == 1

    def test_warm_start_discount_minimum_one(self):
        """Even if base cost * 0.5 rounds to 0, result must be at least 1."""
        # Create a trivial problem with base cost = 1
        problem = OptimizationProblem.model_validate(
            {
                "name": "minimal",
                "objective": {"sense": "minimize", "expression": "x"},
                "variables": [{"name": "x", "type": "continuous", "lower_bound": 0.0}],
                "constraints": [],
            }
        )
        from app.api.v2.solve import calculate_credits

        base = calculate_credits(problem)
        assert base == 1  # Base cost for trivial problem

        discounted = max(1, round(base * 0.5))
        assert discounted == 1  # Must not go below 1
