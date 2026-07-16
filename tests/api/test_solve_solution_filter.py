"""Compact-solution responses for programmatic callers — P1.5 G7d.

``solution_filter=nonzero`` on the solve endpoints omits near-zero variables
from the RESPONSE (an MCP agent's token budget dies on a few hundred zero
binaries) while the persisted execution keeps the full solution.
"""

from app.models.optimization_model import ModelExecution

# min x + y  s.t.  x >= 4, with x,y >= 0  →  x* = 4, y* = 0 (guaranteed zero).
_LP_WITH_ZERO = {
    "name": "solution_filter_lp",
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0.0},
        {"name": "y", "type": "continuous", "lower_bound": 0.0},
    ],
    "constraints": [{"expression": "x >= 4"}],
    "objective": {"expression": "x + y", "sense": "minimize"},
    "options": {"time_limit_seconds": 30, "verbose": False},
}


class TestSolveSolutionFilter:
    """solution_filter on POST /api/v2/solve."""

    def test_nonzero_filter_omits_zero_variables(self, authenticated_client) -> None:
        response = authenticated_client.post(
            "/api/v2/solve?solution_filter=nonzero", json=_LP_WITH_ZERO
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "optimal"

        assert "x" in data["solution"]
        assert "y" not in data["solution"]
        names = [v["name"] for v in data["variables"]]
        assert names == ["x"]
        assert data["variables_omitted"] == 1

    def test_filter_is_presentation_only_full_solution_persisted(
        self, authenticated_client, db_session
    ) -> None:
        """The stored execution keeps EVERY variable — the filter shapes the response."""
        response = authenticated_client.post(
            "/api/v2/solve?solution_filter=nonzero", json=_LP_WITH_ZERO
        )
        assert response.status_code == 200
        execution_id = response.json()["execution_id"]

        db_session.expire_all()
        execution = db_session.get(ModelExecution, execution_id)
        assert execution is not None
        stored_solution = (execution.result_data or {}).get("model") or {}
        assert set(stored_solution) == {"x", "y"}

    def test_default_returns_full_solution(self, authenticated_client) -> None:
        response = authenticated_client.post("/api/v2/solve", json=_LP_WITH_ZERO)
        assert response.status_code == 200
        data = response.json()
        assert set(data["solution"]) == {"x", "y"}
        assert data.get("variables_omitted") is None

    def test_invalid_filter_value_is_rejected(self, authenticated_client) -> None:
        response = authenticated_client.post(
            "/api/v2/solve?solution_filter=bogus", json=_LP_WITH_ZERO
        )
        assert response.status_code == 422


class TestProjectSolveSolutionFilter:
    """solution_filter on POST /api/v2/projects/{id}/solve (the MCP solve tool)."""

    def test_project_solve_supports_nonzero_filter(self, authenticated_client) -> None:
        created = authenticated_client.post("/api/v2/projects", json={"name": "Filter probe"})
        assert created.status_code == 201, created.text
        pid = created.json()["id"]
        put = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _LP_WITH_ZERO}
        )
        assert put.status_code == 200, put.text

        response = authenticated_client.post(
            f"/api/v2/projects/{pid}/solve?solution_filter=nonzero"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "optimal"
        assert "y" not in data["solution"]
        assert data["variables_omitted"] == 1
