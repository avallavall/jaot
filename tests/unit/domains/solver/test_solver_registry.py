"""Test stubs for SOLV-03 — SolverRegistry API.

These tests are Wave 0 stubs (RED phase). They will fail at import time or
assertion time because app.domains.solver.adapters does not yet exist.
Plan 01 must turn them green.
"""

import pytest

# Helper factory — builds a minimal fake adapter conforming to SolverAdapter


def _make_fake_adapter(
    name: str = "fake",
    is_available: bool = True,
) -> object:
    """Return a minimal structural SolverAdapter conformant object."""
    from app.domains.solver.adapters.base import SolverCapabilities
    from app.schemas.optimization import OptimizationResult, SolverStatus

    class _FakeAdapter:
        capabilities = SolverCapabilities(
            name=name,
            supports_continuous=True,
            supports_integer=True,
            supports_binary=True,
            supports_quadratic=False,
            supports_sensitivity=False,
            supports_warm_start=False,
            supports_multi_objective=False,
        )

        def __init__(self) -> None:
            self._available = is_available

        def is_available(self) -> bool:
            return self._available

        def solve(self, problem, *, warm_start=None) -> OptimizationResult:
            return OptimizationResult(
                status=SolverStatus.OPTIMAL,
                solve_time_seconds=0.001,
                objective_value=1.0,
                solution={},
            )

    return _FakeAdapter()


@pytest.mark.unit
def test_registry_register_and_get() -> None:
    """register() followed by get() must return the same adapter instance."""
    from app.domains.solver.adapters import registry

    fake = _make_fake_adapter(name="fake", is_available=True)
    registry.register("fake", fake)

    result = registry.get("fake")
    assert result is fake, "registry.get('fake') must return the registered adapter instance"


@pytest.mark.unit
def test_registry_get_not_found_raises() -> None:
    """get() with an unregistered name must raise SolverNotFoundError."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.adapters.base import SolverNotFoundError

    with pytest.raises(SolverNotFoundError) as exc_info:
        registry.get("nonexistent")

    assert "nonexistent" in str(exc_info.value).lower(), (
        "SolverNotFoundError message must contain the solver name"
    )


@pytest.mark.unit
def test_registry_get_unavailable_raises() -> None:
    """get() for an adapter where is_available() is False must raise SolverUnavailableError."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.adapters.base import SolverUnavailableError

    unavailable = _make_fake_adapter(name="unavail", is_available=False)
    registry.register("unavail", unavailable)

    with pytest.raises(SolverUnavailableError):
        registry.get("unavail")


@pytest.mark.unit
def test_registry_list_available_filters() -> None:
    """list_available() must return only adapters where is_available() is True."""
    from app.domains.solver.adapters import registry

    available = _make_fake_adapter(name="avail", is_available=True)
    unavailable = _make_fake_adapter(name="unavail", is_available=False)

    registry.register("avail", available)
    registry.register("unavail", unavailable)

    result = registry.list_available()
    assert len(result) == 1, (
        f"list_available() must return only the available adapter, got {len(result)}"
    )
    assert result[0].name == "avail", (
        f"The available adapter must be 'avail', got '{result[0].name}'"
    )


@pytest.mark.unit
def test_registry_reset() -> None:
    """reset() must clear all registered adapters."""
    from app.domains.solver.adapters import registry
    from app.domains.solver.adapters.base import SolverNotFoundError

    fake = _make_fake_adapter(name="fake", is_available=True)
    registry.register("fake", fake)

    registry.reset()

    with pytest.raises(SolverNotFoundError):
        registry.get("fake")


@pytest.mark.unit
def test_registry_name_normalization() -> None:
    """Registering with uppercase name must be retrievable via lowercase key."""
    from app.domains.solver.adapters import registry

    fake = _make_fake_adapter(name="scip", is_available=True)
    registry.register("SCIP", fake)

    result = registry.get("scip")
    assert result is fake, (
        "registry.get('scip') must find an adapter registered as 'SCIP' (case normalization)"
    )


@pytest.mark.unit
def test_default_bootstrap_registers_scip() -> None:
    """register_default_adapters() must register 'scip' in the registry (D-09)."""
    from app.domains.solver.adapters import register_default_adapters, registry

    register_default_adapters()

    available = registry.list_available()
    names = [cap.name for cap in available]

    assert "scip" in names, f"register_default_adapters() must register 'scip'. Found: {names}"
