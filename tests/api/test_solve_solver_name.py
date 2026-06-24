"""Tests for solver_name parameter propagation and persistence — Phase 5 / HIGH-04, HIGH-07.

RED until Plan 02 (HiGHSAdapter) + Plan 03 (propagation + migration) complete.
"""


def _minimal_lp_payload(solver_name: str | None = None) -> dict:
    """Minimal LP problem payload for solve endpoint tests."""
    payload = {
        "name": "test_solver_name_lp",
        "variables": [
            {"name": "x", "type": "continuous", "lower_bound": 0.0},
            {"name": "y", "type": "continuous", "lower_bound": 0.0},
        ],
        "constraints": [
            {"expression": "x + y >= 4"},
        ],
        "objective": {"expression": "x + y", "sense": "minimize"},
        "options": {"time_limit_seconds": 30, "verbose": False},
    }
    if solver_name is not None:
        payload["solver_name"] = solver_name
    return payload


class TestSolveWithSolverName:
    """solver_name parameter on POST /api/v2/solve."""

    def test_solve_with_highs_routes_correctly(self, authenticated_client) -> None:
        """solver_name=highs uses HiGHS adapter and returns OPTIMAL."""
        response = authenticated_client.post(
            "/api/v2/solve",
            json=_minimal_lp_payload(solver_name="highs"),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "optimal"

    def test_invalid_solver_returns_422(self, authenticated_client) -> None:
        """solver_name with unknown solver returns HTTP 422."""
        response = authenticated_client.post(
            "/api/v2/solve",
            json=_minimal_lp_payload(solver_name="nonexistent_solver"),
        )
        assert response.status_code == 422
        detail = response.json().get("detail") or response.json().get("message") or ""
        assert "not available" in detail.lower() or "nonexistent_solver" in detail.lower()

    def test_solver_name_persisted(self, authenticated_client, db_session) -> None:
        """solver_name is persisted in ModelExecution.solver_name after solve."""
        response = authenticated_client.post(
            "/api/v2/solve",
            json=_minimal_lp_payload(solver_name="highs"),
        )
        assert response.status_code == 200
        data = response.json()
        execution_id = data.get("execution_id")
        assert execution_id is not None

        from app.models.optimization_model import ModelExecution  # noqa: PLC0415

        exe = db_session.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
        assert exe is not None
        assert exe.solver_name == "highs"
