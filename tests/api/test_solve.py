"""
Tests for Universal Solve API endpoint.

These tests verify the solve functionality:
- Solving optimization problems
- Template-based solving
- Error handling
"""


class TestSolveEndpoint:
    """Tests for POST /api/v2/solve endpoint."""

    def test_solve_requires_auth(self, client):
        """Test that solve requires authentication."""
        response = client.post(
            "/api/v2/solve",
            json={
                "name": "test",
                "objective": {"sense": "maximize", "expression": "x"},
                "variables": [{"name": "x", "type": "continuous"}],
                "constraints": [],
            },
        )
        assert response.status_code == 401

    def test_solve_invalid_problem(self, authenticated_client, db_session, test_organization):
        """Test solve with invalid problem definition."""
        response = authenticated_client.post(
            "/api/v2/solve",
            json={
                "name": "invalid",
                # Missing required fields
            },
        )

        assert response.status_code == 422  # Validation error
