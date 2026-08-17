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


class TestComparableFlag:
    """D-31: the listing says which solvers can take part in a comparison.

    The picker used to offer every available solver, Hexaly included, and Hexaly
    can never compete on this server: it needs its own image and licence, and
    the comparison worker runs the base image so one machine times every column.
    The user found out after spending the launch.
    """

    # CONTRACT-TEST: the flag is derived from the server's own exclusion list,
    # never from a copy. A second list in the API layer would drift the first
    # time a solver moved in or out of PERMANENTLY_EXCLUDED.
    def test_flag_follows_the_servers_exclusion_list(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.domains.solver.adapters import hexaly_availability
        from app.domains.solver.services import worker_health
        from app.domains.solver.services.comparison_service import PERMANENTLY_EXCLUDED

        monkeypatch.setattr(worker_health, "_probe_hexaly_worker", lambda: (True, "ok"))
        monkeypatch.setattr(hexaly_availability, "hexaly_available", lambda: False)

        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200

        for entry in response.json()["solvers"]:
            excluded = PERMANENTLY_EXCLUDED.get(entry["name"])
            assert entry["comparable"] is (excluded is None), (
                f"{entry['name']} disagrees with PERMANENTLY_EXCLUDED"
            )
            if excluded is None:
                assert "not_comparable_reason" not in entry
            else:
                assert entry["not_comparable_reason"] == excluded

    def test_the_solvers_that_can_compare_say_so(self, authenticated_client) -> None:
        """The in-image solvers are always listed and always comparable.

        Only SCIP and HiGHS are asserted by name. CBC and GLPK are command-line
        programs that report their own absence through ``is_available()``, so an
        image built without the binaries lists neither — which is right, and
        which is why naming them here would make this test a statement about the
        image rather than about the flag.
        """
        response = authenticated_client.get("/api/v2/solvers/available")
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        for name in ("scip", "highs"):
            assert by_name[name]["comparable"] is True, f"{name} must be comparable"


class TestVersionReporting:
    """Each solver's own version, so a stored comparison stays explainable.

    A comparison records the machine it ran on. Six months and a rebuilt image
    later, that is not enough: seconds measured against CBC 2.10.12 say nothing
    about 2.11, and a table with no version on it cannot say which one it timed.
    """

    def test_the_in_image_solvers_report_a_version(self, authenticated_client) -> None:
        response = authenticated_client.get("/api/v2/solvers/available")
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        for name in ("scip", "highs"):
            assert by_name[name].get("version"), f"{name} reported no version"

    # A version that cannot be read is absent, never invented and never an
    # error: the listing exists to let a client pick a solver, and it must not
    # start failing because a binary declined to introduce itself.
    def test_an_unreadable_version_is_absent_not_fatal(
        self, authenticated_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.domains.solver.adapters import registry

        scip = registry.get("scip")
        monkeypatch.setattr(type(scip), "version", lambda _self: None)

        response = authenticated_client.get("/api/v2/solvers/available")
        assert response.status_code == 200
        by_name = {s["name"]: s for s in response.json()["solvers"]}
        assert "version" not in by_name["scip"]
