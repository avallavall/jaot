"""Unit tests for SOLVER_QUEUE_MAP and resolve_queue() (Phase 6 INF-01).

Wave 0 RED — these tests will FAIL until app/shared/core/queue_routing.py is
created. Task 2 of plan 06-01 turns them green.

Covers D-01, D-02, D-17 decisions from 06-CONTEXT.md.
"""

import pytest


@pytest.mark.unit
def test_solver_queue_map_contains_scip_highs_and_hexaly() -> None:
    """D-02 + D-17: map must contain scip, highs, and (Phase 7) hexaly.

    Phase 7 landed ``"hexaly": "solve_hexaly"``; future commercial
    solvers (gurobi, cplex) remain explicit extension points.
    """
    from app.domains.solver.queue_routing import SOLVER_QUEUE_MAP

    assert SOLVER_QUEUE_MAP["scip"] == "solve_scip"
    assert SOLVER_QUEUE_MAP["highs"] == "solve_highs"
    assert SOLVER_QUEUE_MAP["hexaly"] == "solve_hexaly"
    # Future extension points must not be pre-reserved.
    assert "gurobi" not in SOLVER_QUEUE_MAP
    assert "cplex" not in SOLVER_QUEUE_MAP


@pytest.mark.unit
def test_resolve_queue_maps_scip_highs_and_hexaly() -> None:
    """D-02 + D-17: explicit solver_name maps to the correct queue."""
    from app.domains.solver.queue_routing import resolve_queue

    assert resolve_queue("scip") == "solve_scip"
    assert resolve_queue("highs") == "solve_highs"
    assert resolve_queue("hexaly") == "solve_hexaly"


@pytest.mark.unit
def test_resolve_queue_defaults_to_scip_when_none() -> None:
    """D-02: None defaults to scip (no-breaking HIGH-04)."""
    from app.domains.solver.queue_routing import resolve_queue

    assert resolve_queue(None) == "solve_scip"


@pytest.mark.unit
def test_resolve_queue_raises_on_unknown_solver() -> None:
    """D-02: unknown solver_name raises SolverNotFoundError (not KeyError)."""
    from app.domains.solver.adapters.base import SolverNotFoundError
    from app.domains.solver.queue_routing import resolve_queue

    with pytest.raises(SolverNotFoundError, match="Unknown solver"):
        resolve_queue("gurobi")


@pytest.mark.unit
def test_solver_not_found_error_message_is_opaque() -> None:
    """WR-03 regression lock: SolverNotFoundError message must not enumerate
    installed solvers.

    Prevents re-introduction of the supported-solver list leak in
    SolverNotFoundError. A future refactor might "helpfully" restore
    `f"Unknown solver '{name}'. Supported: {', '.join(SOLVER_QUEUE_MAP)}"` —
    this test fails loudly in that case.

    Locks in the fix at app/domains/solver/queue_routing.py:35.
    """
    from app.domains.solver.adapters.base import SolverNotFoundError
    from app.domains.solver.queue_routing import resolve_queue

    with pytest.raises(SolverNotFoundError) as exc_info:
        resolve_queue("gurobi")

    message = str(exc_info.value)

    # Client must see what they asked for and a generic rejection.
    assert "Unknown solver" in message
    assert "gurobi" in message

    # Must NOT enumerate installed solvers.
    assert "Supported:" not in message, (
        f"WR-03 regressed: message leaks 'Supported:' marker: {message!r}"
    )
    assert "scip" not in message.lower(), (
        f"WR-03 regressed: message leaks installed solver 'scip': {message!r}"
    )
    assert "highs" not in message.lower(), (
        f"WR-03 regressed: message leaks installed solver 'highs': {message!r}"
    )


@pytest.mark.unit
def test_solver_not_found_error_opacity_holds_when_solver_map_grows(
    monkeypatch,
) -> None:
    """WR-03 regression lock (future-proof): adding commercial solvers to
    SOLVER_QUEUE_MAP must not cause the 422 message to leak their names.

    Prevents re-introduction of the supported-solver list leak in
    SolverNotFoundError. Simulates the Phase 7 extension where
    hexaly/gurobi/cplex land in SOLVER_QUEUE_MAP. The error for an UNKNOWN
    name must still be opaque about which commercial solvers are installed
    on this deployment.

    Locks in the fix at app/domains/solver/queue_routing.py:35.
    """
    from app.domains.solver import queue_routing
    from app.domains.solver.adapters.base import SolverNotFoundError

    extended_map = dict(queue_routing.SOLVER_QUEUE_MAP)
    extended_map["hexaly_pretend_installed"] = "solve_hexaly"
    extended_map["gurobi_pretend_installed"] = "solve_gurobi"
    extended_map["cplex_pretend_installed"] = "solve_cplex"
    monkeypatch.setattr(queue_routing, "SOLVER_QUEUE_MAP", extended_map)

    with pytest.raises(SolverNotFoundError) as exc_info:
        queue_routing.resolve_queue("totally_bogus_solver")

    message = str(exc_info.value)
    assert "totally_bogus_solver" in message

    # Critical: message must NOT reveal that hexaly/gurobi/cplex are installed.
    lowered = message.lower()
    assert "hexaly" not in lowered, (
        f"WR-03 regressed: message leaks commercial solver 'hexaly': {message!r}"
    )
    assert "gurobi" not in lowered, (
        f"WR-03 regressed: message leaks commercial solver 'gurobi': {message!r}"
    )
    assert "cplex" not in lowered, (
        f"WR-03 regressed: message leaks commercial solver 'cplex': {message!r}"
    )
    assert "Supported:" not in message, (
        f"WR-03 regressed: message leaks 'Supported:' marker: {message!r}"
    )


@pytest.mark.unit
def test_wr03_unknown_solver_does_not_leak_hexaly() -> None:
    """Phase 7 / D-17: after hexaly lands in SOLVER_QUEUE_MAP, the WR-03 guard still holds.

    Plan 07-07 adds ``"hexaly": "solve_hexaly"`` to the real map. An unknown
    solver request must still return an opaque error that does NOT reveal
    that hexaly is installed on this deployment — otherwise clients could
    fingerprint commercial SDK availability via 422 responses.
    """
    from app.domains.solver.adapters.base import SolverNotFoundError
    from app.domains.solver.queue_routing import resolve_queue

    with pytest.raises(SolverNotFoundError) as excinfo:
        resolve_queue("bogus_commercial_xyz")
    detail = str(excinfo.value).lower()
    # The unknown name is echoed back (user-supplied, not privileged info).
    assert "bogus_commercial_xyz" in detail
    # The installed set stays opaque.
    assert "scip" not in detail
    assert "highs" not in detail
    assert "hexaly" not in detail
    assert "supported:" not in detail
