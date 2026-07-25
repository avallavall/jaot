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


class TestSolverCapabilitiesExposed:
    """v3.2: the listing exposes what each solver can actually deliver.

    Before this, ``SolverCapabilities`` had no consumer outside the adapters, so
    the UI offered the same analysis surface for every solver.
    """

    # CONTRACT-TEST: every listed solver carries the four UI-actionable
    # capability flags, so a panel can decline itself with a reason.
    def test_every_listed_solver_reports_the_ui_capability_flags(
        self, authenticated_client
    ) -> None:
        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        solvers = response.json()["solvers"]
        assert solvers, "expected at least the in-image solvers"
        for solver in solvers:
            caps = solver["capabilities"]
            assert set(caps) == {"sensitivity", "warm_start", "quadratic", "progress"}
            assert all(isinstance(v, bool) for v in caps.values())

    def test_capabilities_match_the_adapter_declaration(self, authenticated_client) -> None:
        """The payload mirrors the adapters — it is not a second source of truth.

        Asserting against the registry (rather than hard-coding True/False here)
        means an adapter that changes what it supports cannot drift away from
        what the UI is told without this test moving with it.
        """
        from app.domains.solver.adapters import registry

        declared = {cap.name: cap for cap in registry.list_available()}
        response = authenticated_client.get("/api/v2/solvers/available")
        by_name = {s["name"]: s for s in response.json()["solvers"]}

        for name, cap in declared.items():
            caps = by_name[name]["capabilities"]
            assert caps["sensitivity"] is cap.supports_sensitivity
            assert caps["warm_start"] is cap.supports_warm_start
            assert caps["quadratic"] is cap.supports_quadratic
            assert caps["progress"] is cap.supports_progress

    # CONTRACT-TEST: supports_multi_objective stays OUT of the payload. It flags
    # NATIVE support and is False on every adapter, while the orchestrator gives
    # every solver multi-objective via scalarization — exposing it would tell the
    # user a solver cannot do something it demonstrably can.
    def test_multi_objective_is_not_exposed(self, authenticated_client) -> None:
        response = authenticated_client.get("/api/v2/solvers/available")
        for solver in response.json()["solvers"]:
            assert "multi_objective" not in solver["capabilities"]

    def test_scip_reports_sensitivity_and_progress(self, authenticated_client) -> None:
        """The reference adapter is the one the analysis surface was built on."""
        response = authenticated_client.get("/api/v2/solvers/available")
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        assert by_name["scip"]["capabilities"]["sensitivity"] is True
        assert by_name["scip"]["capabilities"]["progress"] is True

    def test_highs_declines_live_progress(self, authenticated_client) -> None:
        """highspy exposes no per-incumbent callback, so Live Solve cannot stream."""
        response = authenticated_client.get("/api/v2/solvers/available")
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        assert by_name["highs"]["capabilities"]["progress"] is False
        assert by_name["highs"]["capabilities"]["sensitivity"] is True
