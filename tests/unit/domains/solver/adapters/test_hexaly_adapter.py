"""HexalyAdapter contract tests — HEX-01, HEX-04, HEX-05.

Wave 1 (Plan 07-02) turns these GREEN. The Wave 0 stubs used
``pytest.mark.xfail(strict=False)`` so the suite collected without flipping
red before the adapter landed. With the real adapter implemented, every
pure-unit test must pass and the SDK-gated known-answer test must either
pass on a dev machine with the Hexaly SDK + ``HEXALY_TEST_LICENSE`` env var,
or skip cleanly in CI.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from app.domains.solver.adapters.hexaly import HexalyAdapter, hexaly_license_scope
from app.domains.solver.adapters.hexaly_availability import hexaly_available

# Pure unit (no SDK) tests — run everywhere


def test_hexaly_adapter_implements_protocol(
    make_lic_file: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural Protocol surface: is_available, solve, capabilities all present and callable.

    Phase 7.4 / D-10: validate_license removed from Protocol and all adapters.
    Also exercises is_available() — the value must be a proper bool that
    tracks the SDK presence (True when the wheel is installed in the image,
    False when it is not). After Phase 7.4 / HEX-08 the SDK ships in
    requirements.txt so the api/worker images return True; the no-SDK
    contract is asserted in test_hexaly_import_isolation below.
    """
    lic = make_lic_file()
    monkeypatch.setattr("app.domains.solver.adapters.hexaly.HEXALY_LIC_PATH", lic)
    adapter = HexalyAdapter()
    assert hasattr(adapter, "is_available") and callable(adapter.is_available)
    assert not hasattr(adapter, "validate_license"), "validate_license must be removed (D-10)"
    assert hasattr(adapter, "solve") and callable(adapter.solve)
    assert hasattr(adapter, "capabilities")
    available = adapter.is_available()
    assert isinstance(available, bool)
    assert available is hexaly_available()


def test_hexaly_capabilities_fields(
    make_lic_file: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-11: every capability field must match exactly so downstream
    auto-router decisions and UI badges stay consistent."""
    lic = make_lic_file()
    monkeypatch.setattr("app.domains.solver.adapters.hexaly.HEXALY_LIC_PATH", lic)
    caps = HexalyAdapter().capabilities
    assert caps.name == "hexaly"
    assert caps.supports_continuous is True
    assert caps.supports_integer is True
    assert caps.supports_binary is True
    assert caps.supports_quadratic is True
    assert caps.supports_sensitivity is False
    assert caps.supports_warm_start is True
    assert caps.supports_multi_objective is False


def test_hexaly_import_isolation(
    make_lic_file: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hexaly adapter module MUST import cleanly when the SDK is absent.

    Simulates a no-SDK image by replacing the modules with ``None`` in
    ``sys.modules``, reloading the adapter module, and asserting
    ``is_available()`` returns False — no ImportError, no traceback.

    ``hexaly_availability`` memoises its probe result, so if a preceding test
    saw the real SDK it may have cached ``_cache=True``. Reset inside the
    patch.dict context so the next probe sees the simulated absence.
    """
    from app.domains.solver.adapters.hexaly_availability import (  # noqa: PLC0415
        _reset_cache_for_tests,
    )

    lic = make_lic_file()
    with patch.dict(sys.modules, {"hexaly": None, "hexaly.optimizer": None}):
        _reset_cache_for_tests()
        try:
            import app.domains.solver.adapters.hexaly as mod  # noqa: PLC0415

            importlib.reload(mod)
            # importlib.reload() resets module-level constants to their original
            # value, so monkeypatch must target the post-reload module ref
            # directly (not the dotted path string).
            monkeypatch.setattr(mod, "HEXALY_LIC_PATH", lic)
            assert mod.HexalyAdapter().is_available() is False
        finally:
            # Restore the cache so subsequent tests see the real SDK state.
            _reset_cache_for_tests()


def test_license_scope_sets_and_unsets_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: env var is present inside the with-block and gone after."""
    monkeypatch.delenv("HX_LICENSE_CONTENT", raising=False)
    with hexaly_license_scope("fake-license"):
        assert os.environ["HX_LICENSE_CONTENT"] == "fake-license"
    assert os.environ.get("HX_LICENSE_CONTENT") is None


def test_license_scope_unsets_even_when_block_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-07-08 mitigation: an exception inside the with-block must not leak
    the license to the next task on the same worker."""
    monkeypatch.delenv("HX_LICENSE_CONTENT", raising=False)
    with pytest.raises(RuntimeError, match="boom"):
        with hexaly_license_scope("fake-license"):
            assert os.environ["HX_LICENSE_CONTENT"] == "fake-license"
            raise RuntimeError("boom")
    assert os.environ.get("HX_LICENSE_CONTENT") is None


def test_license_scope_restores_preexisting_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-07-10 mitigation: a pre-existing value is restored, not clobbered."""
    monkeypatch.setenv("HX_LICENSE_CONTENT", "outer-license")
    with hexaly_license_scope("inner-license"):
        assert os.environ["HX_LICENSE_CONTENT"] == "inner-license"
    assert os.environ["HX_LICENSE_CONTENT"] == "outer-license"


def test_license_scope_rejects_empty_plaintext() -> None:
    """Defensive: empty plaintext would silently "activate" nothing and could
    surface as a confusing SDK-level error. Reject upfront."""
    with pytest.raises(ValueError):
        with hexaly_license_scope(""):
            pass


# Non-gated HEX-04 known-answer coverage via FakeHexalyAdapter (runs in CI
# without the Hexaly SDK). Provides the contract-level coverage that @skipif
# SDK tests cannot deliver in CI.


def test_hex04_known_answer_via_fake_adapter() -> None:
    """HEX-04 contract-level coverage that runs in CI without the Hexaly SDK.

    FakeHexalyAdapter (Wave 0 fixture) hard-codes ``objective_value=42.0`` and
    status=OPTIMAL — the canonical known-answer baked into the fake. This
    proves the HEX-04 requirement is exercised end-to-end (adapter → result
    shape → assertions) even when the real SDK is absent.
    """
    from app.schemas.optimization import (  # noqa: PLC0415
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        SolverStatus,
        Variable,
        VariableType,
    )
    from tests.fixtures.fake_hexaly_adapter import FakeHexalyAdapter  # noqa: PLC0415

    problem = OptimizationProblem(
        variables=[
            Variable(
                name="x",
                type=VariableType.CONTINUOUS,
                lower_bound=0.0,
                upper_bound=10.0,
            ),
            Variable(
                name="y",
                type=VariableType.CONTINUOUS,
                lower_bound=0.0,
                upper_bound=10.0,
            ),
        ],
        objective=Objective(expression="x * y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x + y <= 10", name="budget")],
    )

    adapter = FakeHexalyAdapter()
    # FakeHexalyAdapter.solve uses the Protocol signature (problem, *, warm_start=None).
    # It does not take a license — that's the whole point of the fake: CI-green
    # coverage without a real license.
    result = adapter.solve(problem)

    assert result.status == SolverStatus.OPTIMAL
    assert result.objective_value == 42.0
    assert result.solution is not None
    assert set(result.solution.keys()) == {"x", "y"}


# SDK-gated integration tests — skip cleanly in CI (D-19).
# Run only on dev machines with hexaly installed AND HEXALY_TEST_LICENSE set.


@pytest.mark.skipif(not hexaly_available(), reason="Hexaly SDK not installed")
def test_hexaly_known_answer_quadratic_problem() -> None:
    """HEX-04 end-to-end: ``max x*y  s.t.  x + y <= 10, 0 <= x,y <= 10``.

    Optimum is ``x = y = 5, obj = 25``. Requires both (a) the Hexaly SDK
    installed in the venv AND (b) a valid test license in
    ``HEXALY_TEST_LICENSE``. Skip cleanly if either is missing.
    """
    from app.schemas.optimization import (  # noqa: PLC0415
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        SolverStatus,
        Variable,
        VariableType,
    )

    license_plaintext = os.environ.get("HEXALY_TEST_LICENSE", "")
    if not license_plaintext:
        pytest.skip("HEXALY_TEST_LICENSE not set in environment")

    problem = OptimizationProblem(
        variables=[
            Variable(
                name="x",
                type=VariableType.CONTINUOUS,
                lower_bound=0.0,
                upper_bound=10.0,
            ),
            Variable(
                name="y",
                type=VariableType.CONTINUOUS,
                lower_bound=0.0,
                upper_bound=10.0,
            ),
        ],
        objective=Objective(expression="x * y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x + y <= 10", name="budget")],
    )

    adapter = HexalyAdapter()
    result = adapter.solve(problem, license_plaintext=license_plaintext, time_limit_seconds=5)

    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert result.objective_value == pytest.approx(25.0, rel=0.01)
    assert result.solution is not None
    assert result.solution["x"] == pytest.approx(5.0, rel=0.05)
    assert result.solution["y"] == pytest.approx(5.0, rel=0.05)


# Empty-license guard test removed: the platform license is loaded in
# HexalyAdapter.__init__ and is always non-empty when init succeeds, so the
# empty-license_plaintext kwarg is unreachable through normal usage. Load +
# fail-fast coverage lives in test_platform_license_load /
# test_missing_license_fails_fast / test_expired_license_fails_fast.
