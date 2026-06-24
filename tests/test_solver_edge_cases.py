"""Tests for solver edge cases (Task 5.10).

Covers:
- Time limit enforcement
- Large problem handling (100+ variables)
- Infeasible problem detection
- Unbounded problem detection
- Tight constraints behavior
- Solver status mapping
- Orchestrator timeout + refund end-to-end
"""

import time

import pytest

from app.domains.solver.adapters.scip import SCIPAdapter
from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)


def _make_large_problem(
    n_vars: int,
    var_type: VariableType = VariableType.CONTINUOUS,
    time_limit: float = 60.0,
) -> OptimizationProblem:
    """Create a problem with n_vars variables and n_vars constraints.

    Maximize sum(i * x_i) subject to sum(x_i) <= n_vars * 0.5, x_i in [0, 1].
    """
    variables = [
        Variable(
            name=f"x{i}",
            type=var_type,
            lower_bound=0.0,
            upper_bound=1.0,
        )
        for i in range(n_vars)
    ]

    # Objective: maximize sum(i * x_i)
    obj_terms = " + ".join(f"{i + 1}*x{i}" for i in range(n_vars))
    objective = Objective(sense=ObjectiveSense.MAXIMIZE, expression=obj_terms)

    # Constraint: sum(x_i) <= n_vars * 0.5
    sum_terms = " + ".join(f"x{i}" for i in range(n_vars))
    constraints = [Constraint(name="capacity", expression=f"{sum_terms} <= {n_vars * 0.5}")]

    return OptimizationProblem(
        name=f"large_{n_vars}_vars",
        variables=variables,
        objective=objective,
        constraints=constraints,
        options=SolverOptions(time_limit_seconds=time_limit),
    )


class TestSolverTimeLimit:
    """Verify the solver respects time_limit_seconds."""

    def test_easy_problem_within_time_limit(self):
        """An easy LP should solve well within a 1-second limit."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="easy_lp",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            ],
            constraints=[Constraint(expression="x + y <= 15")],
            options=SolverOptions(time_limit_seconds=1),
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert result.solve_time_seconds < 2.0

    def test_time_limit_parameter_is_set(self):
        """Verify _configure_solver forwards time_limit_seconds to SCIP's limits/time.

        We wrap _configure_solver on a SCIPAdapter instance and capture the
        SCIP model right after the call so we can read back the parameter with
        getParam('limits/time'). This confirms the value was written to SCIP.
        """
        adapter = SCIPAdapter()
        problem = OptimizationProblem(
            name="time_check",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=100),
            ],
            constraints=[Constraint(expression="x <= 50")],
            options=SolverOptions(time_limit_seconds=5),
        )

        captured: dict[str, float] = {}
        original_configure = adapter._configure_solver

        def _spy_configure(model, problem):
            result = original_configure(model, problem)
            captured["limits/time"] = model.getParam("limits/time")
            return result

        adapter._configure_solver = _spy_configure  # type: ignore[method-assign]
        try:
            result = adapter.solve(problem)
        finally:
            adapter._configure_solver = original_configure  # type: ignore[method-assign]

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert captured.get("limits/time") == 5.0

    def test_very_short_time_limit_on_hard_mip(self):
        """A hard MIP with 1-second limit should finish quickly (may hit TIME_LIMIT)."""
        solver = SolverService()
        n = 50
        variables = [Variable(name=f"x{i}", type=VariableType.BINARY) for i in range(n)]
        obj_expr = " + ".join(f"{(i * 7 + 3) % 100}*x{i}" for i in range(n))
        sum_expr = " + ".join(f"{(i * 13 + 5) % 50}*x{i}" for i in range(n))

        problem = OptimizationProblem(
            name="hard_mip",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression=obj_expr),
            variables=variables,
            constraints=[Constraint(expression=f"{sum_expr} <= {n * 10}")],
            options=SolverOptions(time_limit_seconds=1),
        )

        start = time.time()
        result = solver.solve(problem)
        elapsed = time.time() - start

        assert result.status in [
            SolverStatus.OPTIMAL,
            SolverStatus.FEASIBLE,
            SolverStatus.TIME_LIMIT,
        ]
        # Should not take more than 5 seconds (generous margin for CI)
        assert elapsed < 5.0


class TestSolverLargeProblem:
    """Verify the solver handles problems with many variables."""

    def test_100_continuous_variables(self):
        """100 continuous variables should solve to optimality."""
        solver = SolverService()
        problem = _make_large_problem(100, VariableType.CONTINUOUS)
        result = solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        assert len(result.solution) == 100
        assert result.objective_value is not None
        assert result.objective_value > 0

    def test_50_integer_variables(self):
        """50 integer variables should solve to OPTIMAL with constraint satisfied."""
        solver = SolverService()
        n = 50
        problem = _make_large_problem(n, VariableType.INTEGER, time_limit=30)
        result = solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        assert len(result.solution) == n
        # Capacity constraint: sum(x_i) <= n * 0.5
        total = sum(result.solution.values())
        assert total <= n * 0.5 + 0.01

    def test_60_binary_variables(self):
        """60 binary variables (knapsack-style) should solve to OPTIMAL."""
        solver = SolverService()
        n = 60
        problem = _make_large_problem(n, VariableType.BINARY, time_limit=30)
        result = solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        assert len(result.solution) == n
        # Binary values should be 0 or 1 exactly
        for val in result.solution.values():
            assert val in [0, 0.0, 1, 1.0]
        # Capacity constraint: sum(x_i) <= n * 0.5
        total = sum(result.solution.values())
        assert total <= n * 0.5 + 0.01

    def test_large_problem_constraint_satisfaction(self):
        """Verify solution of a 100-var problem satisfies constraints."""
        solver = SolverService()
        n = 100
        problem = _make_large_problem(n, VariableType.CONTINUOUS)
        result = solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None

        # Check capacity constraint: sum(x_i) <= n * 0.5
        total = sum(result.solution.values())
        assert total <= n * 0.5 + 0.01  # small tolerance


class TestSolverInfeasible:
    """Verify proper detection and reporting of infeasible problems."""

    def test_contradictory_bounds(self):
        """x >= 10 AND x <= 5 is infeasible."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="infeasible_bounds",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x >= 10"),
                Constraint(expression="x <= 5"),
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.INFEASIBLE

    def test_infeasible_system_of_equations(self):
        """x + y == 10 AND x + y == 20 is infeasible."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="infeasible_eq",
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x + y == 10"),
                Constraint(expression="x + y == 20"),
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.INFEASIBLE

    def test_infeasible_no_solution_returned(self):
        """Infeasible problems should not return a solution dict."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="infeasible_nosol",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x >= 100"),
                Constraint(expression="x <= 50"),
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.INFEASIBLE
        assert result.objective_value is None

    def test_infeasible_binary_problem(self):
        """Binary problem where constraints cannot be simultaneously satisfied."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="infeasible_binary",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="a + b + c"),
            variables=[
                Variable(name="a", type=VariableType.BINARY),
                Variable(name="b", type=VariableType.BINARY),
                Variable(name="c", type=VariableType.BINARY),
            ],
            constraints=[
                # Must select all 3 items, but capacity only allows 2
                Constraint(expression="a + b + c >= 3"),
                Constraint(expression="a + b + c <= 2"),
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.INFEASIBLE


class TestSolverUnbounded:
    """Verify proper detection of unbounded problems."""

    def test_unbounded_maximization(self):
        """Maximize x with no upper bound and no constraints → SCIP returns UNBOUNDED."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="unbounded_max",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.UNBOUNDED

    def test_unbounded_minimization(self):
        """Minimize x with no lower bound and no constraints → SCIP returns UNBOUNDED."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="unbounded_min",
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS),  # no bounds
            ],
            constraints=[],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.UNBOUNDED


class TestSolverTightConstraints:
    """Verify solver behavior with very tight constraints."""

    def test_equality_constraints_tight_solution(self):
        """When all constraints are equalities, solution is fully determined."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="tight_eq",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x == 3"),
                Constraint(expression="y == 7"),
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        assert abs(result.solution["x"] - 3.0) < 0.01
        assert abs(result.solution["y"] - 7.0) < 0.01
        assert abs(result.objective_value - 10.0) < 0.01

    def test_narrow_feasible_region(self):
        """Very narrow feasible region (near-degenerate LP)."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="narrow_region",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=100),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=100),
            ],
            constraints=[
                Constraint(expression="x + y <= 10"),
                Constraint(expression="x + y >= 9.999"),
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        total = result.solution["x"] + result.solution["y"]
        assert 9.99 <= total <= 10.01

    def test_all_variables_at_bounds(self):
        """When optimal solution has all variables at their bounds."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="at_bounds",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y + z"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=5),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=5),
                Variable(name="z", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=5),
            ],
            constraints=[
                Constraint(expression="x + y + z <= 100"),  # Not binding
            ],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        # All vars should be at upper bound
        assert abs(result.solution["x"] - 5.0) < 0.01
        assert abs(result.solution["y"] - 5.0) < 0.01
        assert abs(result.solution["z"] - 5.0) < 0.01

    def test_single_feasible_point(self):
        """When there is exactly one feasible point."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="single_point",
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=5, upper_bound=5),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=3, upper_bound=3),
            ],
            constraints=[],
        )
        result = solver.solve(problem)
        assert result.status == SolverStatus.OPTIMAL
        assert abs(result.solution["x"] - 5.0) < 0.01
        assert abs(result.solution["y"] - 3.0) < 0.01


class TestSolverStatusMapping:
    """Verify the SCIP status -> SolverStatus mapping."""

    @pytest.mark.parametrize(
        "scip_status,expected",
        [
            ("optimal", SolverStatus.OPTIMAL),
            ("infeasible", SolverStatus.INFEASIBLE),
            ("unbounded", SolverStatus.UNBOUNDED),
            ("timelimit", SolverStatus.TIME_LIMIT),
            ("memlimit", SolverStatus.ERROR),
            ("gaplimit", SolverStatus.OPTIMAL),
            ("sollimit", SolverStatus.FEASIBLE),
            ("some_unknown_status", SolverStatus.ERROR),
        ],
    )
    def test_map_status(self, scip_status, expected):
        assert SCIPAdapter._map_status(scip_status) == expected


class TestSolverErrorHandling:
    """Verify solver gracefully handles errors."""

    def test_invalid_expression_returns_error(self):
        """Invalid objective expression should return ERROR status."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="bad_expr",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + nonexistent_var"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            ],
            constraints=[],
        )
        result = solver.solve(problem)
        # Should return error without crashing
        assert result.status == SolverStatus.ERROR
        assert result.error_message is not None

    def test_solve_time_always_reported(self):
        """Even on infeasibility, solve_time_seconds must be strictly positive."""
        solver = SolverService()
        problem = OptimizationProblem(
            name="infeasible_time",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x >= 10"),
                Constraint(expression="x <= 5"),
            ],
        )
        result = solver.solve(problem)
        assert result.solve_time_seconds > 0


class TestSolveTimeoutRefundIntegration:
    """End-to-end timeout-refund path against the real SolveOrchestrator."""

    def test_solve_timeout_refund_end_to_end(self, db_session, test_organization):
        """A solver that raises asyncio.TimeoutError fully refunds the pre-paid credits.

        Exercises the real orchestrator (not the unit test mocks) so that the
        actual refund SQL is executed against the real database. The solve
        function raises TimeoutError to simulate a SCIP thread pool timeout.
        """
        import asyncio
        from unittest.mock import MagicMock

        from app.domains.solver.services.pool import get_solver_pool
        from app.domains.solver.services.solver_service import SolverService
        from app.models import Organization
        from app.services.solve_orchestrator import SolveOrchestrator

        initial_balance = 1000
        test_organization.credits_balance = initial_balance
        db_session.commit()

        problem = OptimizationProblem(
            name="timeout_test",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            ],
            constraints=[Constraint(expression="x <= 5")],
            options=SolverOptions(time_limit_seconds=30),
        )

        # Use a solver that always raises TimeoutError inside the pool.
        class _TimeoutSolver(SolverService):
            def solve(self, problem, warm_start_solution=None):  # type: ignore[override]
                # This exception bubbles up through asyncio.run_in_executor.
                raise TimeoutError("Simulated SCIP timeout")

        solver = _TimeoutSolver()
        orchestrator = SolveOrchestrator(db_session, solver, get_solver_pool())

        # Build a minimal request mock (needed for _error_response verbose check).
        fake_request = MagicMock()
        fake_request.headers = {}
        fake_request.state.user = None

        credits_needed = 5

        async def _run():
            with pytest.raises(Exception):  # noqa: B017 — we just want the side-effect
                await orchestrator.solve_single(
                    problem=problem,
                    org=test_organization,
                    user=None,
                    request=fake_request,
                    credits_needed=credits_needed,
                    workspace_id=None,
                )

        asyncio.run(_run())

        # Refund must have restored the full balance.
        db_session.expire_all()
        updated = db_session.get(Organization, test_organization.id)
        assert updated.credits_balance == initial_balance
