"""Phase 7.4 / D-12 / D-11 — /solvers/available exposes worker health."""

from __future__ import annotations

import pytest


class TestSolversAvailableOptionalSdk:
    """The Hexaly SDK is an optional extra (requirements-hexaly.txt) — the API
    image normally runs WITHOUT it. The listing must reflect the real worker,
    not the local SDK."""

    # CONTRACT-TEST: a healthy Hexaly worker makes hexaly listable even when
    # the API process has no SDK installed (OSS deploy with `hexaly` profile).
    def test_healthy_worker_lists_hexaly_without_local_sdk(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.domains.solver.adapters import hexaly_availability
        from app.domains.solver.services import worker_health

        monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (True, "ok"))
        monkeypatch.setattr(hexaly_availability, "hexaly_available", lambda: False)

        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        assert "hexaly" in by_name
        assert by_name["hexaly"]["available"] is True

    # CONTRACT-TEST: the synthesised hexaly entry reads its capabilities from
    # HexalyAdapter itself. hexaly.py imports the SDK lazily and `capabilities`
    # is a class attribute, so this needs neither the proprietary SDK nor the
    # .lic that __init__ fail-fasts on — keeping ONE source of truth instead of
    # a copy in the route that would silently rot.
    def test_synthesised_hexaly_carries_the_adapters_own_capabilities(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.domains.solver.adapters import hexaly_availability
        from app.domains.solver.adapters.hexaly import HexalyAdapter
        from app.domains.solver.services import worker_health

        monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (True, "ok"))
        monkeypatch.setattr(hexaly_availability, "hexaly_available", lambda: False)

        response = authenticated_client.get("/api/v2/solvers/available")
        caps = {s["name"]: s for s in response.json()["solvers"]}["hexaly"]["capabilities"]

        declared = HexalyAdapter.capabilities
        assert caps["sensitivity"] is declared.supports_sensitivity
        assert caps["warm_start"] is declared.supports_warm_start
        assert caps["quadratic"] is declared.supports_quadratic
        assert caps["progress"] is declared.supports_progress
        # And the substantive fact the UI acts on: Hexaly is a metaheuristic, so
        # it computes no duals and streams no per-incumbent progress.
        assert caps["sensitivity"] is False
        assert caps["progress"] is False

    # CONTRACT-TEST: listing must never regress into HIDING a solver because its
    # capabilities could not be read. Availability and capability are independent.
    def test_unreadable_capabilities_still_list_the_solver(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api.v2 import solvers as solvers_route
        from app.domains.solver.adapters import hexaly_availability, registry
        from app.domains.solver.services import worker_health

        if "hexaly" in {cap.name for cap in registry.list_available()}:
            pytest.skip("Hexaly adapter registered for real on this host (license present)")

        monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (True, "ok"))
        monkeypatch.setattr(hexaly_availability, "hexaly_available", lambda: False)
        monkeypatch.setattr(solvers_route, "_hexaly_capabilities", lambda: None)

        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        assert by_name["hexaly"]["available"] is True
        # No capabilities key rather than a fabricated one: the consumer falls
        # back to claiming nothing.
        assert "capabilities" not in by_name["hexaly"]

    def test_no_worker_and_no_sdk_hides_hexaly(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.domains.solver.adapters import hexaly_availability, registry
        from app.domains.solver.services import worker_health

        if "hexaly" in {cap.name for cap in registry.list_available()}:
            pytest.skip("Hexaly adapter registered for real on this host (license present)")

        monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (False, "down"))
        monkeypatch.setattr(hexaly_availability, "hexaly_available", lambda: False)

        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        assert "hexaly" not in by_name
        # The open-source default (SCIP + HiGHS) is always present
        assert "scip" in by_name
        assert "highs" in by_name
