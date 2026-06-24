"""Phase 7.4 / D-10 — validate_license removed from SolverAdapter Protocol."""

from __future__ import annotations


def test_validate_license_removed_from_protocol() -> None:
    """V-11: SolverAdapter Protocol does NOT define validate_license; no
    adapter (SCIP, HiGHS, Hexaly) implements it as an instance method.
    (Phase 7.4 / Plan 03 Task 3)"""
    from app.domains.solver.adapters.base import SolverAdapter
    from app.domains.solver.adapters.hexaly import HexalyAdapter
    from app.domains.solver.adapters.highs import HiGHSAdapter
    from app.domains.solver.adapters.scip import SCIPAdapter

    # Protocol must not declare the method
    assert "validate_license" not in dir(SolverAdapter)
    # No adapter retains the method
    for adapter_cls in (SCIPAdapter, HiGHSAdapter, HexalyAdapter):
        assert not hasattr(adapter_cls, "validate_license"), (
            f"{adapter_cls.__name__} still implements validate_license"
        )
