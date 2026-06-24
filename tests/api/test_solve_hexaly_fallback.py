"""Phase 7.4 / D-11 — auto + quadratic + Hexaly down → SCIP + warning."""

from __future__ import annotations

import pytest


def test_auto_quadratic_fallback_returns_warning(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V-17: auto + quadratic + Hexaly worker unavailable → solver_used='scip',
    auto_route_reason='hexaly_unavailable_fallback', warning field present.
    (Phase 7.4 / Plan 05 Task 3)"""
    from app.domains.solver.services import worker_health

    monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (False, "test_off"))
    # /api/v2/solve takes OptimizationProblem fields flat (not nested under "problem")
    payload = {
        "name": "qp_fallback",
        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0}],
        "constraints": [{"name": "c1", "expression": "x >= 1"}],
        "objective": {"expression": "x*x", "sense": "minimize"},
        "options": {"time_limit_seconds": 10.0, "verbose": False},
        "solver_name": "auto",
    }
    response = authenticated_client.post("/api/v2/solve", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body.get("solver_used") == "scip"
    assert body.get("auto_route_reason") == "hexaly_unavailable_fallback"
    assert "warning" in body
    assert "Hexaly temporarily unavailable" in body["warning"]
