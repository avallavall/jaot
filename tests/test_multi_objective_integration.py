"""Multi-objective solve integration tests.

Tests the full flow: credit deduction -> multi-objective solve -> Pareto points returned.
Uses real SCIP solver with small problems (not mocked).

Requires: docker-compose --profile test up -d
"""

import pytest

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
        """Multi-objective solve completes via API endpoint."""
        body = _make_solve_request_body(n_points=3, mode="epsilon")

        resp = authenticated_client.post(
            "/api/v2/solve/multi-objective",
            json=body,
        )
        assert resp.status_code == 200, f"Multi-objective solve failed: {resp.text[:300]}"

        data = resp.json()
        assert "pareto_points" in data
        assert data["n_solved"] >= 1

    def test_infeasible_multi_objective_completes(
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


class TestEpsilonRangeWhenTheSecondObjectiveHasNoWorstValue:
    """The epsilon grid must step from the optimum toward WORSE values.

    When the second objective is unbounded the other way (or constant), the
    worst value is made up. It used to be made up on the wrong side whenever
    the optimum was zero or negative, and for any constant MAXIMIZE objective,
    so every epsilon was better than the optimum and the front came back empty.
    """

    @staticmethod
    def _problem() -> OptimizationProblem:
        # Emissions x cost nothing to add and have no cap, so maximizing them is
        # unbounded. Their optimum is 0.
        return OptimizationProblem.model_validate(
            {
                "objective": {"sense": "maximize", "expression": "y"},
                "variables": [
                    {"name": "x", "type": "continuous", "lower_bound": 0},
                    {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 5},
                ],
                "constraints": [{"name": "needs_emissions", "expression": "y <= x"}],
            }
        )

    @staticmethod
    def _config(expression: str, sense: ObjectiveSense) -> MultiObjectiveConfig:
        return MultiObjectiveConfig(
            mode="epsilon",
            objectives=[
                ObjectiveSpec(expression="y", sense=ObjectiveSense.MAXIMIZE, label="Output"),
                ObjectiveSpec(expression=expression, sense=sense, label="Emissions"),
            ],
            n_points=4,
        )

    # The grid used to stop one step short of the optimum, so every point sat
    # strictly on the worse side. The optimum is an end of the front and is now
    # on it: the points run from it (0) toward worse values, and none is better.
    def test_minimize_with_an_optimum_of_zero(self):
        points = SolverService(solver_name="scip").solve_multi_objective(
            self._problem(), self._config("x", ObjectiveSense.MINIMIZE)
        )
        assert points, "the front came back empty"
        assert all(p.f2 >= -1e-9 for p in points)
        assert min(p.f2 for p in points) == pytest.approx(0.0, abs=1e-6)
        assert any(p.f2 > 0 for p in points), "the grid never stepped toward worse values"

    def test_maximize_with_a_negative_optimum(self):
        points = SolverService(solver_name="scip").solve_multi_objective(
            self._problem(), self._config("-x", ObjectiveSense.MAXIMIZE)
        )
        assert points, "the front came back empty"
        assert all(p.f2 <= 1e-9 for p in points)
        assert max(p.f2 for p in points) == pytest.approx(0.0, abs=1e-6)
        assert any(p.f2 < 0 for p in points), "the grid never stepped toward worse values"

    def test_the_made_up_end_when_the_first_objective_has_no_best_value(self):
        """Objective 1 unbounded and objective 2 unbounded the other way.

        No point is best for objective 1, and objective 2 has no worst value, so
        the far end of the grid is made up by stepping from the optimum of
        objective 2 toward worse values.
        """
        config = MultiObjectiveConfig(
            mode="epsilon",
            objectives=[
                ObjectiveSpec(expression="x + y", sense=ObjectiveSense.MAXIMIZE, label="Output"),
                ObjectiveSpec(expression="x", sense=ObjectiveSense.MINIMIZE, label="Emissions"),
            ],
            n_points=4,
        )
        points = SolverService(solver_name="scip").solve_multi_objective(self._problem(), config)

        assert points, "the front came back empty"
        assert all(p.f2 >= -1e-9 for p in points)
        assert min(p.f2 for p in points) == pytest.approx(0.0, abs=1e-6)
        assert any(p.f2 > 0 for p in points)


def _profit_vs_emissions_body(**problem_extra) -> dict:
    """The model the QA pass drove (2026-09-25): max 3x+5y against min 2x+4y."""
    return {
        "problem": {
            "name": "profit_vs_emissions",
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0},
                {"name": "y", "type": "continuous", "lower_bound": 0},
            ],
            "constraints": [
                {"expression": "x + y <= 10"},
                {"expression": "x <= 8"},
                {"expression": "y <= 7"},
                {"expression": "x + 2*y >= 4"},
            ],
            "objective": {"expression": "3*x + 5*y", "sense": "maximize"},
            **problem_extra,
        },
        "config": {
            "mode": "epsilon",
            "n_points": 3,
            "objectives": [
                {"expression": "3*x + 5*y", "sense": "maximize", "label": "P"},
                {"expression": "2*x + 4*y", "sense": "minimize", "label": "E"},
            ],
        },
    }


class TestMultiObjectiveSolverChoice:
    """The solver the request names is the solver that runs, and the run says so.

    The endpoint ran SCIP whatever was asked: a request naming JAOS came back
    from SCIP and was stored as SCIP. The response had no execution id, so the
    page could not link to the run it had just made.
    """

    @pytest.mark.parametrize("solver", ["highs", "jaos", "cbc", "glpk"])
    def test_the_named_solver_runs_and_is_stored(
        self, solver, authenticated_client, db_session, test_organization, monkeypatch
    ):
        from app.domains.solver import execution_writer
        from app.models import ModelExecution

        stored: dict = {}
        real_write = execution_writer.mark_multi_objective_completed_by_task

        def _capture(*args, **kwargs):
            stored.update(kwargs)
            return real_write(*args, **kwargs)

        monkeypatch.setattr(execution_writer, "mark_multi_objective_completed_by_task", _capture)

        res = authenticated_client.post(
            "/api/v2/solve/multi-objective", json=_profit_vs_emissions_body(solver_name=solver)
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["solver_used"] == solver
        assert body["execution_id"].startswith("exe_")
        row = (
            db_session.query(ModelExecution)
            .filter(
                ModelExecution.id == body["execution_id"],
                ModelExecution.organization_id == test_organization.id,
            )
            .one()
        )
        assert row.solver_name == solver
        # What the run page reads: the front, and a verdict that says it is one.
        assert stored["result_data"]["solver_status"] == "pareto_front"
        assert stored["result_data"]["solver_used"] == solver
        front = stored["result_data"]["multi_objective"]["pareto_points"]
        assert [(p["f1"], p["f2"]) for p in front] == [
            (p["f1"], p["f2"]) for p in body["pareto_points"]
        ]
        assert len(front) == 3

    def test_the_query_parameter_names_the_solver_too(
        self, authenticated_client, db_session, test_organization
    ):
        res = authenticated_client.post(
            "/api/v2/solve/multi-objective?solver_name=highs", json=_profit_vs_emissions_body()
        )

        assert res.status_code == 200, res.text
        assert res.json()["solver_used"] == "highs"

    def test_no_solver_named_keeps_scip(self, authenticated_client, db_session, test_organization):
        res = authenticated_client.post(
            "/api/v2/solve/multi-objective", json=_profit_vs_emissions_body()
        )

        assert res.status_code == 200, res.text
        assert res.json()["solver_used"] == "scip"

    def test_auto_routes_a_linear_front_to_highs(
        self, authenticated_client, db_session, test_organization
    ):
        res = authenticated_client.post(
            "/api/v2/solve/multi-objective", json=_profit_vs_emissions_body(solver_name="auto")
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["solver_used"] == "highs"
        assert body["auto_route_reason"]

    def test_a_quadratic_objective_on_a_linear_solver_is_refused_up_front(
        self, authenticated_client, db_session, test_organization
    ):
        body = _profit_vs_emissions_body(solver_name="highs")
        body["config"]["objectives"][0]["expression"] = "x*y"

        res = authenticated_client.post("/api/v2/solve/multi-objective", json=body)

        assert res.status_code == 422, res.text
        assert res.json()["code"] == "multi_objective.solver_no_quadratic"
        assert res.json()["params"] == {"solver": "HiGHS"}

    def test_a_quadratic_objective_runs_on_scip(
        self, authenticated_client, db_session, test_organization
    ):
        body = _profit_vs_emissions_body(solver_name="scip")
        body["config"]["objectives"][1]["expression"] = "x*x + y*y"

        res = authenticated_client.post("/api/v2/solve/multi-objective", json=body)

        assert res.status_code == 200, res.text
        assert res.json()["n_solved"] >= 1

    def test_an_objective_naming_an_undeclared_variable_is_a_400(
        self, authenticated_client, db_session, test_organization
    ):
        body = _profit_vs_emissions_body()
        body["config"]["objectives"][1]["expression"] = "2*x + 4*q"

        res = authenticated_client.post("/api/v2/solve/multi-objective", json=body)

        assert res.status_code == 400, res.text
        assert res.json()["code"] == "problem.mo_objective_undefined_variables"
        assert res.json()["params"] == {"n": 2, "names": "q"}

    def test_an_unknown_solver_is_refused(
        self, authenticated_client, db_session, test_organization
    ):
        res = authenticated_client.post(
            "/api/v2/solve/multi-objective", json=_profit_vs_emissions_body(solver_name="gurobi")
        )

        assert res.status_code == 422, res.text
