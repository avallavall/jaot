"""Phase 7.4 / D-11 — direct solver_name='hexaly' + worker down → 503."""

from __future__ import annotations

import pytest


def test_direct_hexaly_unavailable_returns_503(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V-16: solver_name='hexaly' with Hexaly worker unavailable returns
    503 with body {"error": "solver_unavailable", "solver": "hexaly", ...}.
    (Phase 7.4 / Plan 05 Task 3)"""
    from app.domains.solver.services import worker_health

    monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (False, "test_off"))
    # /api/v2/solve takes OptimizationProblem fields flat (not nested under "problem")
    payload = {
        "name": "direct_hexaly_unavailable_test",
        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0}],
        "constraints": [{"name": "c1", "expression": "x >= 1"}],
        "objective": {"expression": "x", "sense": "minimize"},
        "options": {"time_limit_seconds": 10.0, "verbose": False},
        "solver_name": "hexaly",
    }
    response = authenticated_client.post("/api/v2/solve", json=payload)
    assert response.status_code == 503
    # FastAPI wraps HTTPException.detail under a "detail" key
    body = response.json()
    detail = body.get("detail", body)  # handle both wrapped and flat shapes
    assert detail.get("error") == "solver_unavailable"
    assert detail.get("solver") == "hexaly"
    assert "message" in detail
