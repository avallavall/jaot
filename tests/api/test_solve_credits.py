"""Phase 7.4 / PRC-01 — calculate_credits multiplies by per-solver PSS multiplier."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _build_problem(num_vars: int = 10, time_limit_seconds: float = 60.0):
    from app.schemas.optimization import (
        Constraint,
        Objective,
        OptimizationProblem,
        SolverOptions,
        Variable,
        VariableType,
    )

    return OptimizationProblem(
        name="credits_test",
        variables=[
            Variable(name=f"x{i}", type=VariableType.CONTINUOUS, lower_bound=0.0)
            for i in range(num_vars)
        ],
        constraints=[Constraint(expression="x0 >= 1")],
        objective=Objective(expression="x0", sense="minimize"),
        options=SolverOptions(time_limit_seconds=time_limit_seconds, verbose=False),
    )


def test_no_solver_returns_base() -> None:
    """V-08: calculate_credits(problem) (no solver_name) returns base credits
    (multiplier defaults to 1.0)."""
    from app.api.v2.solve import calculate_credits

    base = calculate_credits(_build_problem())
    assert base >= 1


def test_hexaly_multiplier() -> None:
    """V-08: calculate_credits(problem, solver_name='hexaly', db=mock) multiplies
    base credits by PSS pricing.solver_multiplier.hexaly."""
    from app.api.v2.solve import calculate_credits
    from app.services.platform_settings_service import PlatformSettingsService as PSS

    mock_db = MagicMock()
    # PSS.get_float reads from DB; mock it to return the registry default (5.0)
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
        PSS, "get_float", return_value=5.0
    ):
        base = calculate_credits(_build_problem())
        hexaly = calculate_credits(_build_problem(), solver_name="hexaly", db=mock_db)
    # Default Hexaly multiplier from settings_registry is 5.0
    assert hexaly == max(1, round(base * 5.0))


def test_hexaly_costs_5x_scip_integration(authenticated_client) -> None:
    """V-08 (integration): same problem, hexaly solver_name costs 5x scip
    in persisted credit charge (proves the multiplier reaches the debit
    end-to-end through /api/v2/solve, not just the unit-level calculator).

    Skipped when Hexaly worker not available — local dev / CI without
    a .lic file should not block this assertion (covered by mock-PSS
    test_hexaly_multiplier above). (Phase 7.4 / Plan 04 Task 2)"""
    # /api/v2/solve takes OptimizationProblem fields flat (not nested under "problem")
    base_payload = {
        "name": "multiplier_integration_test",
        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0}],
        "constraints": [{"name": "c1", "expression": "x >= 1"}],
        "objective": {"expression": "x", "sense": "minimize"},
        "options": {"time_limit_seconds": 5.0, "verbose": False},
    }
    scip_resp = authenticated_client.post(
        "/api/v2/solve", json={**base_payload, "solver_name": "scip"}
    )
    assert scip_resp.status_code == 200
    scip_credits = scip_resp.json()["credits_used"]

    hexaly_resp = authenticated_client.post(
        "/api/v2/solve", json={**base_payload, "solver_name": "hexaly"}
    )
    if hexaly_resp.status_code == 503:
        pytest.skip("Hexaly worker unavailable in this environment")
    assert hexaly_resp.status_code == 200
    hexaly_credits = hexaly_resp.json()["credits_used"]
    assert hexaly_credits == max(1, round(scip_credits * 5.0)), (
        f"Expected hexaly={scip_credits * 5}, got hexaly={hexaly_credits}"
    )
