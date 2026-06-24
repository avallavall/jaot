"""Tests for GET /api/v2/solvers/available — Phase 5 / HIGH-05.

Phase 7.4 / D-11 update: the endpoint now also surfaces hexaly with a
variable ``available`` flag (False when celery_worker_hexaly is down).
This file covers the SCIP + HiGHS shape only — the hexaly availability
contract lives in tests/api/test_solvers_available.py.
"""


class TestSolversAvailableEndpoint:
    """GET /api/v2/solvers/available tests."""

    def test_list_available_returns_scip_and_highs(self, authenticated_client) -> None:
        """Authenticated request returns SCIP and HiGHS with available=True.

        Phase 7.4 / D-11: hexaly may also appear with ``available=False`` when
        the worker is down — that path is asserted in test_solvers_available.py.
        Here we only verify the in-image solvers (SCIP + HiGHS) are listed and
        marked available, since they ship in every image and never depend on a
        runtime worker probe.
        """
        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        data = response.json()
        assert "solvers" in data
        by_name = {s["name"]: s for s in data["solvers"]}
        assert "scip" in by_name
        assert "highs" in by_name
        for name in ("scip", "highs"):
            solver = by_name[name]
            assert solver["available"] is True
            assert "description" in solver
            assert isinstance(solver["description"], str)
            assert len(solver["description"]) > 0

    def test_requires_auth(self, client) -> None:
        """Unauthenticated request returns 401."""
        response = client.get("/api/v2/solvers/available")
        assert response.status_code == 401
