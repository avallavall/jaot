"""Phase 7.4 / D-12 / D-11 — /solvers/available exposes multiplier + worker health."""

from __future__ import annotations

import pytest


class TestSolversAvailableMultiplier:
    def test_lists_multipliers_per_solver(self, authenticated_client) -> None:
        """V-04: each solver entry includes a 'multiplier' float field.
        (Phase 7.4 / Plan 07 Task 1)"""
        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        for solver in response.json()["solvers"]:
            assert "multiplier" in solver
            assert isinstance(solver["multiplier"], (int, float))
        # Defaults from settings_registry: scip=1.0, highs=1.2, hexaly=5.0
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        if "scip" in by_name:
            assert by_name["scip"]["multiplier"] == 1.0
        if "highs" in by_name:
            assert by_name["highs"]["multiplier"] == 1.2
        if "hexaly" in by_name:
            assert by_name["hexaly"]["multiplier"] == 5.0

    def test_hexaly_availability_reflects_worker_health(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """V-04: when Hexaly worker probe returns False, hexaly entry has
        available=False and reason='maintenance'. (Phase 7.4 / Plan 07 Task 1)"""
        from app.domains.solver.services import worker_health

        monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (False, "test_off"))
        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        if "hexaly" in by_name:
            assert by_name["hexaly"]["available"] is False
            assert by_name["hexaly"]["reason"] == "maintenance"


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
        assert by_name["hexaly"]["multiplier"] == 5.0

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
