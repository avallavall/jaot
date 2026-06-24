"""Test stubs for SOLV-07 — multi-objective orchestration via stub adapter.

These tests are Wave 0 stubs (RED phase). They verify that SolverService
delegates multi-objective scalarization to adapter.solve() — never to direct
SCIP API calls. They will fail until Plan 03 (full SCIP extraction) lands.

Key invariant (D-02): the orchestrator builds fresh OptimizationProblem
instances for each scalarized subproblem and calls adapter.solve() on each.
No SCIP-specific API must be called outside of adapters/scip.py.
"""

from __future__ import annotations

import pytest

from app.schemas.optimization import (
    Constraint,
    MultiObjectiveConfig,
    Objective,
    ObjectiveSense,
    ObjectiveSpec,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
    Variable,
    VariableType,
)

# Helper: build a two-variable, two-objective problem and config


def _make_two_obj_problem() -> OptimizationProblem:
    """Return a minimal two-variable problem for multi-objective tests."""
    return OptimizationProblem(
        name="multi_obj_test",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
        constraints=[
            Constraint(name="budget", expression="x + y <= 5"),
        ],
    )


def _make_weighted_config(n_points: int = 3) -> MultiObjectiveConfig:
    """Return a weighted-scalarization multi-objective config."""
    return MultiObjectiveConfig(
        mode="weighted",
        objectives=[
            ObjectiveSpec(expression="x", sense=ObjectiveSense.MAXIMIZE, label="obj1"),
            ObjectiveSpec(expression="y", sense=ObjectiveSense.MAXIMIZE, label="obj2"),
        ],
        n_points=n_points,
    )


def _make_epsilon_config(n_points: int = 3) -> MultiObjectiveConfig:
    """Return an epsilon-constraint multi-objective config."""
    return MultiObjectiveConfig(
        mode="epsilon",
        objectives=[
            ObjectiveSpec(expression="x", sense=ObjectiveSense.MAXIMIZE, label="obj1"),
            ObjectiveSpec(expression="y", sense=ObjectiveSense.MAXIMIZE, label="obj2"),
        ],
        n_points=n_points,
    )


# Fake adapter that records every solve() call


class _RecordingFakeAdapter:
    """Structural SolverAdapter conformant stub that records solve() calls."""

    def __init__(self) -> None:
        from app.domains.solver.adapters.base import SolverCapabilities

        self.capabilities = SolverCapabilities(
            name="fake",
            supports_continuous=True,
            supports_integer=True,
            supports_binary=True,
            supports_quadratic=False,
            supports_sensitivity=False,
            supports_warm_start=False,
            supports_multi_objective=False,
        )
        self.solve_calls: list[OptimizationProblem] = []

    def is_available(self) -> bool:
        return True

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
    ) -> OptimizationResult:
        self.solve_calls.append(problem)
        return OptimizationResult(
            status=SolverStatus.OPTIMAL,
            solve_time_seconds=0.001,
            objective_value=5.0,
            solution={"x": 1.0, "y": 2.0},
        )


@pytest.mark.unit
def test_weighted_fallback_calls_adapter_solve() -> None:
    """Weighted-sum orchestration must call adapter.solve() at least n_points times."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.services.solver_service import SolverService

    problem = _make_two_obj_problem()
    config = _make_weighted_config(n_points=3)

    fake = _RecordingFakeAdapter()
    registry.register("fake", fake)

    service = SolverService(solver_name="fake")
    service.solve_multi_objective(problem, config)

    assert len(fake.solve_calls) >= 3, (
        f"Weighted fallback must call adapter.solve() at least 3 times "
        f"(one per weight point), got {len(fake.solve_calls)}"
    )

    # Every subproblem must be a distinct instance (orchestrator never reuses)
    ids = [id(p) for p in fake.solve_calls]
    assert len(ids) == len(set(ids)), (
        "Each recorded solve call must receive a distinct OptimizationProblem instance"
    )


@pytest.mark.unit
def test_weighted_fallback_never_touches_pyscipopt() -> None:
    """Scalarized subproblems must use plain expression strings — no SCIP API references."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.services.solver_service import SolverService

    problem = _make_two_obj_problem()
    config = _make_weighted_config(n_points=3)

    fake = _RecordingFakeAdapter()
    registry.register("fake", fake)

    service = SolverService(solver_name="fake")
    service.solve_multi_objective(problem, config)

    assert len(fake.solve_calls) >= 1, "At least one subproblem must be solved"

    first_problem = fake.solve_calls[0]

    # The scalarized objective expression must be a non-empty string
    assert isinstance(first_problem.objective.expression, str)
    assert len(first_problem.objective.expression) > 0, (
        "Scalarized objective expression must be non-empty"
    )

    # Must NOT contain any SCIP-specific API references (expression strings only)
    scip_markers = ["model.setObjective", "addCons", "addVar", ".optimize("]
    for marker in scip_markers:
        assert marker not in first_problem.objective.expression, (
            f"Scalarized problem expression must not contain SCIP API reference '{marker}'"
        )


@pytest.mark.unit
def test_epsilon_constraint_fallback_adds_constraints_per_subproblem() -> None:
    """Epsilon-constraint orchestration must add constraints to each fresh subproblem."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.services.solver_service import SolverService

    problem = _make_two_obj_problem()
    config = _make_epsilon_config(n_points=3)

    fake = _RecordingFakeAdapter()
    registry.register("fake", fake)

    service = SolverService(solver_name="fake")
    service.solve_multi_objective(problem, config)

    base_constraint_count = len(problem.constraints)

    assert len(fake.solve_calls) >= 1, "At least one subproblem must be solved"

    for i, recorded in enumerate(fake.solve_calls):
        assert len(recorded.constraints) >= base_constraint_count, (
            f"Subproblem {i} must have at least {base_constraint_count} constraints "
            f"(epsilon constraint is added per step), got {len(recorded.constraints)}"
        )


@pytest.mark.unit
def test_solver_service_solve_delegates_to_registry() -> None:
    """SolverService.solve() must use the registry to resolve the solver adapter."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.adapters.base import SolverNotFoundError
    from app.domains.solver.services.solver_service import SolverService

    problem = _make_two_obj_problem()

    # Registry is reset by the autouse fixture — 'scip' is not registered
    service = SolverService(solver_name="scip")
    with pytest.raises(SolverNotFoundError):
        service.solve(problem)

    # Now register a fake under 'scip'
    fake = _RecordingFakeAdapter()
    registry.register("scip", fake)

    result = service.solve(problem)

    assert len(fake.solve_calls) == 1, (
        "solve() must delegate exactly once to the registered adapter"
    )
    # The result returned by service must be the result from the adapter
    assert result.status == SolverStatus.OPTIMAL, (
        f"Result from adapter must be propagated unchanged, got {result.status}"
    )
