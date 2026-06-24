"""Test stubs for SOLV-01 — SolverAdapter Protocol contract.

These tests are Wave 0 stubs (RED phase). They will fail at import time or
assertion time because app.domains.solver.adapters.base does not yet exist.
Plan 01 must turn them green.
"""

import inspect
from typing import Protocol

import pytest


@pytest.mark.unit
def test_solver_adapter_is_protocol() -> None:
    """SolverAdapter must be a typing.Protocol with the three required methods."""
    from app.domains.solver.adapters.base import SolverAdapter

    # Verify it is a Protocol
    assert issubclass(SolverAdapter, Protocol), "SolverAdapter must subclass typing.Protocol"

    # Protocol surface: capabilities + is_available + solve.
    assert hasattr(SolverAdapter, "is_available"), "SolverAdapter must define is_available()"
    assert hasattr(SolverAdapter, "solve"), "SolverAdapter must define solve()"


@pytest.mark.unit
def test_solver_adapter_solve_signature() -> None:
    """SolverAdapter.solve must accept (self, problem, *, warm_start=None)."""
    from app.domains.solver.adapters.base import SolverAdapter

    sig = inspect.signature(SolverAdapter.solve)
    params = dict(sig.parameters)

    assert "problem" in params, "solve() must have a 'problem' parameter"
    assert "warm_start" in params, "solve() must have a 'warm_start' parameter"

    warm_start_param = params["warm_start"]
    assert warm_start_param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "warm_start must be a keyword-only argument"
    )
    assert warm_start_param.default is None, "warm_start default must be None"


@pytest.mark.unit
def test_multi_objective_solver_adapter_extends_base() -> None:
    """MultiObjectiveSolverAdapter must extend SolverAdapter and add solve_multi_objective."""
    from app.domains.solver.adapters.base import MultiObjectiveSolverAdapter

    # SolverAdapter must appear in the Protocol's MRO. Python 3.12 does not
    # populate __orig_bases__ for Protocol subclasses, so MRO is the reliable
    # way to assert the hierarchy — semantically equivalent to checking bases.
    mro_names = {c.__name__ for c in MultiObjectiveSolverAdapter.__mro__}
    assert "SolverAdapter" in mro_names, (
        "MultiObjectiveSolverAdapter must list SolverAdapter in its MRO"
    )

    # solve_multi_objective must exist
    assert hasattr(MultiObjectiveSolverAdapter, "solve_multi_objective"), (
        "MultiObjectiveSolverAdapter must define solve_multi_objective()"
    )


@pytest.mark.unit
def test_solver_error_hierarchy() -> None:
    """SolverNotFoundError and SolverUnavailableError must inherit from SolverError."""
    from app.domains.solver.adapters.base import (
        SolverError,
        SolverNotFoundError,
        SolverUnavailableError,
    )

    assert issubclass(SolverError, Exception), "SolverError must subclass Exception"
    assert issubclass(SolverNotFoundError, SolverError), (
        "SolverNotFoundError must subclass SolverError"
    )
    assert issubclass(SolverUnavailableError, SolverError), (
        "SolverUnavailableError must subclass SolverError"
    )
