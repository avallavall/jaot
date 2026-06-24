"""Test stubs for SOLV-04 — SCIPAdapter structural conformance.

These tests are Wave 0 stubs (RED phase). They will fail at import time or
assertion time because app.domains.solver.adapters.scip does not yet exist.
Plans 02 and 03 must turn them green.
"""

import inspect

import pytest


@pytest.mark.unit
def test_scip_adapter_capabilities_fields() -> None:
    """SCIPAdapter.capabilities must expose correct SolverCapabilities values for SCIP."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    adapter = SCIPAdapter()

    assert adapter.capabilities.name == "scip"
    assert adapter.capabilities.supports_continuous is True
    assert adapter.capabilities.supports_integer is True
    assert adapter.capabilities.supports_binary is True
    assert adapter.capabilities.supports_quadratic is True
    assert adapter.capabilities.supports_sensitivity is True
    assert adapter.capabilities.supports_warm_start is True
    assert adapter.capabilities.supports_multi_objective is False


@pytest.mark.unit
def test_scip_adapter_is_available() -> None:
    """SCIPAdapter.is_available() must return True when pyscipopt is installed."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    # pyscipopt is installed in the dev environment, so this must be True
    assert SCIPAdapter().is_available() is True


@pytest.mark.unit
def test_scip_adapter_solve_signature() -> None:
    """SCIPAdapter.solve must accept (self, problem, *, warm_start=None)."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    sig = inspect.signature(SCIPAdapter.solve)
    params = dict(sig.parameters)

    assert "problem" in params, "solve() must have a 'problem' parameter"
    assert "warm_start" in params, "solve() must have a 'warm_start' parameter"

    warm_start_param = params["warm_start"]
    assert warm_start_param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "warm_start must be a keyword-only argument"
    )
    assert warm_start_param.default is None, "warm_start default must be None"


@pytest.mark.unit
def test_scip_adapter_solves_simple_problem() -> None:
    """SCIPAdapter.solve() must solve a simple LP to optimality with correct values."""
    from app.domains.solver.adapters.scip import SCIPAdapter
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        SolverStatus,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        name="simple_lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + 2*y"),
        constraints=[
            Constraint(name="sum_limit", expression="x + y <= 4"),
        ],
    )

    adapter = SCIPAdapter()
    result = adapter.solve(problem)

    assert result.status == SolverStatus.OPTIMAL, f"Expected OPTIMAL, got {result.status}"
    assert result.objective_value == pytest.approx(8.0, abs=1e-6), (
        f"Expected objective 8.0, got {result.objective_value}"
    )
    assert result.solution is not None
    assert result.solution["y"] == pytest.approx(4.0, abs=1e-6), (
        f"Expected y=4.0, got {result.solution['y']}"
    )
    assert result.solution["x"] == pytest.approx(0.0, abs=1e-6), (
        f"Expected x=0.0, got {result.solution['x']}"
    )


@pytest.mark.unit
def test_scip_adapter_accepts_warm_start_kwarg() -> None:
    """SCIPAdapter.solve() must accept warm_start kwarg and report warm_start_used=True."""
    from app.domains.solver.adapters.scip import SCIPAdapter
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        name="warm_start_test",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + 2*y"),
        constraints=[
            Constraint(name="sum_limit", expression="x + y <= 4"),
        ],
    )

    adapter = SCIPAdapter()
    result = adapter.solve(problem, warm_start={"x": 1.0, "y": 2.0})

    assert result.warm_start_used is True, (
        "warm_start_used must be True when warm_start dict is provided (D-01)"
    )
