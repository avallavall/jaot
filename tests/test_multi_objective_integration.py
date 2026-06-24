"""Multi-objective solve integration tests.

Tests the full flow: credit deduction -> multi-objective solve -> Pareto points returned.
Uses real SCIP solver with small problems (not mocked).

Requires: docker-compose --profile test up -d
"""

from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import (
    MultiObjectiveConfig,
    ObjectiveSense,
    ObjectiveSpec,
    OptimizationProblem,
    ParetoPoint,
)


def _make_bi_objective_problem() -> OptimizationProblem:
    """Small bi-objective problem: minimize x and minimize y, x + y >= 10."""
    return OptimizationProblem.model_validate(
        {
            "name": "bi_obj_test",
            "objective": {"sense": "minimize", "expression": "x"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
                {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
            ],
            "constraints": [
                {"name": "sum_bound", "expression": "x + y >= 10"},
            ],
            "options": {"time_limit_seconds": 30},
        }
    )


def _make_epsilon_config(n_points=3) -> MultiObjectiveConfig:
    """Epsilon-constraint config for bi-objective problem."""
    return MultiObjectiveConfig(
        mode="epsilon",
        objectives=[
            ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE, label="Obj_X"),
            ObjectiveSpec(expression="y", sense=ObjectiveSense.MINIMIZE, label="Obj_Y"),
        ],
        n_points=n_points,
    )


def _make_weighted_config(n_points=3) -> MultiObjectiveConfig:
    """Weighted-scalarization config for bi-objective problem."""
    return MultiObjectiveConfig(
        mode="weighted",
        objectives=[
            ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE, label="Obj_X"),
            ObjectiveSpec(expression="y", sense=ObjectiveSense.MINIMIZE, label="Obj_Y"),
        ],
        n_points=n_points,
    )


def _make_solve_request_body(n_points=3, mode="epsilon"):
    """Build a JSON-serializable request body for POST /api/v2/solve/multi-objective."""
    return {
        "problem": {
            "name": "credit-test",
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
                {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
            ],
            "constraints": [{"expression": "x + y >= 10"}],
            "objective": {"expression": "x", "sense": "minimize"},
            "options": {"time_limit_seconds": 30},
        },
        "config": {
            "mode": mode,
            "objectives": [
                {"expression": "x", "sense": "minimize"},
                {"expression": "y", "sense": "minimize"},
            ],
            "n_points": n_points,
        },
    }


class TestMultiObjectiveIntegration:
    """Integration tests for multi-objective solver using real SCIP."""

    def test_epsilon_constraint_returns_pareto_points(self):
        """Epsilon-constraint method returns list of ParetoPoints."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = _make_epsilon_config(n_points=3)

        points = solver.solve_multi_objective(problem, config)
        assert isinstance(points, list)
        assert len(points) >= 1, "Expected at least 1 Pareto point"
        for pt in points:
            assert isinstance(pt, ParetoPoint)
            assert hasattr(pt, "f1")
            assert hasattr(pt, "f2")
            assert isinstance(pt.solution, dict)
            assert "x" in pt.solution
            assert "y" in pt.solution
            assert isinstance(pt.objective_values, dict)

    def test_weighted_mode_returns_pareto_points(self):
        """Weighted scalarization returns list of ParetoPoints."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = _make_weighted_config(n_points=3)

        points = solver.solve_multi_objective(problem, config)
        assert isinstance(points, list)
        assert len(points) >= 1, "Expected at least 1 Pareto point"
        for pt in points:
            assert isinstance(pt, ParetoPoint)
            assert isinstance(pt.solution, dict)

    def test_credits_deducted_after_solve(
        self,
        authenticated_client,
        db_session,
        test_organization,
    ):
        """Multi-objective solve deducts credits via API endpoint."""
        from app.api.v2.solve import calculate_credits
        from app.models import Organization
        from app.schemas.optimization import OptimizationProblem as OP

        # Ensure org has credits
        test_organization.credits_balance = 1000
        db_session.commit()

        body = _make_solve_request_body(n_points=3, mode="epsilon")

        resp = authenticated_client.post(
            "/api/v2/solve/multi-objective",
            json=body,
        )
        assert resp.status_code == 200, f"Multi-objective solve failed: {resp.text[:300]}"

        data = resp.json()
        assert "pareto_points" in data
        assert data["n_solved"] >= 1

        # Verify credits were deducted
        db_session.expire_all()
        updated_org = db_session.get(Organization, test_organization.id)
        assert updated_org.credits_balance < 1000, (
            f"Credits not deducted: balance is still {updated_org.credits_balance}"
        )

        # Verify expected credit cost
        problem = OP.model_validate(body["problem"])
        expected_per_solve = calculate_credits(problem)
        expected_total = expected_per_solve * 3
        actual_deduction = 1000 - updated_org.credits_balance
        assert actual_deduction == expected_total, (
            f"Expected {expected_total} credits deducted, got {actual_deduction}"
        )

    def test_credits_deducted_on_infeasible_multi_objective(
        self,
        authenticated_client,
        db_session,
        test_organization,
    ):
        """Infeasible multi-objective problem still deducts credits (no refund).

        Contract: The orchestrator only refunds on solver ERROR status or a
        thrown exception. Infeasibility in multi-objective returns an empty
        Pareto front (status 200, n_solved=0) and credits stay deducted.
        If this contract changes, this test must be updated to match.
        """
        from app.api.v2.solve import calculate_credits
        from app.models import Organization
        from app.schemas.optimization import OptimizationProblem as OP

        initial_balance = 1000
        test_organization.credits_balance = initial_balance
        db_session.commit()

        # Infeasible: x <= 5 AND x >= 100
        body = {
            "problem": {
                "name": "infeasible-test",
                "variables": [
                    {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 5},
                ],
                "constraints": [
                    {"expression": "x >= 100"},
                ],
                "objective": {"expression": "x", "sense": "minimize"},
                "options": {"time_limit_seconds": 10},
            },
            "config": {
                "mode": "epsilon",
                "objectives": [
                    {"expression": "x", "sense": "minimize"},
                    {"expression": "x", "sense": "maximize"},
                ],
                "n_points": 2,
            },
        }

        resp = authenticated_client.post("/api/v2/solve/multi-objective", json=body)
        assert resp.status_code == 200, (
            f"Infeasible multi-objective got {resp.status_code}: {resp.text[:300]}"
        )

        data = resp.json()
        # Infeasible problem should have 0 pareto points
        assert data["n_solved"] == 0
        assert len(data["pareto_points"]) == 0

        # Credits are NOT refunded on infeasibility (only on ERROR status).
        # Expected deduction = calculate_credits(problem) * n_points.
        expected_per_solve = calculate_credits(OP.model_validate(body["problem"]))
        expected_total = expected_per_solve * body["config"]["n_points"]

        db_session.expire_all()
        updated_org = db_session.get(Organization, test_organization.id)
        assert updated_org.credits_balance == initial_balance - expected_total

    def test_single_point_pareto(self):
        """Trivial feasible region produces consistent Pareto points."""
        solver = SolverService()
        # Problem with very constrained feasible region
        problem = OptimizationProblem.model_validate(
            {
                "name": "trivial_pareto",
                "objective": {"sense": "minimize", "expression": "x"},
                "variables": [
                    {"name": "x", "type": "continuous", "lower_bound": 5, "upper_bound": 5},
                    {"name": "y", "type": "continuous", "lower_bound": 5, "upper_bound": 5},
                ],
                "constraints": [],
                "options": {"time_limit_seconds": 10},
            }
        )
        config = _make_epsilon_config(n_points=2)

        points = solver.solve_multi_objective(problem, config)
        # With a single feasible point, all Pareto points should be the same
        assert len(points) >= 1
        for pt in points:
            assert abs(pt.solution["x"] - 5.0) < 1e-6
            assert abs(pt.solution["y"] - 5.0) < 1e-6

    def test_infeasible_multi_objective(self):
        """Infeasible problem returns empty Pareto front."""
        solver = SolverService()
        problem = OptimizationProblem.model_validate(
            {
                "name": "infeasible_mo",
                "objective": {"sense": "minimize", "expression": "x"},
                "variables": [
                    {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
                ],
                "constraints": [
                    {"expression": "x >= 10"},
                    {"expression": "x <= 0"},
                ],
                "options": {"time_limit_seconds": 10},
            }
        )
        config = MultiObjectiveConfig(
            mode="epsilon",
            objectives=[
                ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE),
                ObjectiveSpec(expression="x", sense=ObjectiveSense.MAXIMIZE),
            ],
            n_points=3,
        )

        points = solver.solve_multi_objective(problem, config)
        assert isinstance(points, list)
        assert len(points) == 0, "Infeasible problem should return empty Pareto front"

    def test_epsilon_constraint_boundary_values(self):
        """Solver handles epsilon values at exact constraint boundaries."""
        solver = SolverService()
        # Tight feasible region: x + y == 10 (effectively a line)
        problem = OptimizationProblem.model_validate(
            {
                "name": "boundary_test",
                "objective": {"sense": "minimize", "expression": "x"},
                "variables": [
                    {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
                    {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
                ],
                "constraints": [
                    {"expression": "x + y == 10"},
                ],
                "options": {"time_limit_seconds": 10},
            }
        )
        config = _make_epsilon_config(n_points=5)

        points = solver.solve_multi_objective(problem, config)
        assert isinstance(points, list)
        assert len(points) >= 1

        # All points should satisfy x + y == 10
        for pt in points:
            total = pt.solution["x"] + pt.solution["y"]
            assert abs(total - 10.0) < 1e-4, (
                f"Point violates x + y == 10: x={pt.solution['x']}, y={pt.solution['y']}"
            )

    def test_pareto_labels_match_config(self):
        """Pareto point objective_values keys match configured labels."""
        solver = SolverService()
        problem = _make_bi_objective_problem()
        config = _make_epsilon_config(n_points=3)

        points = solver.solve_multi_objective(problem, config)
        assert len(points) >= 1
        for pt in points:
            assert "Obj_X" in pt.objective_values
            assert "Obj_Y" in pt.objective_values
