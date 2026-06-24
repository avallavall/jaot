"""Test stubs for SOLV-02 — SolverCapabilities frozen dataclass.

These tests are Wave 0 stubs (RED phase). They will fail at import time or
assertion time because app.domains.solver.adapters.base does not yet exist.
Plan 01 must turn them green.
"""

import dataclasses

import pytest


@pytest.mark.unit
def test_capabilities_is_frozen_dataclass() -> None:
    """SolverCapabilities must be a frozen dataclass — mutation raises FrozenInstanceError."""
    from app.domains.solver.adapters.base import SolverCapabilities

    assert dataclasses.is_dataclass(SolverCapabilities), "SolverCapabilities must be a dataclass"

    caps = SolverCapabilities(
        name="test",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=False,
        supports_sensitivity=True,
        supports_warm_start=True,
        supports_multi_objective=False,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.name = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_capabilities_has_exact_eight_fields() -> None:
    """SolverCapabilities must have exactly 8 fields with the canonical names.

    Phase 7.4 / D-10: ``requires_license`` field removed. Field count drops
    from 9 to 8. License validity is a startup-time adapter concern, not a
    per-request capability flag.
    """
    from app.domains.solver.adapters.base import SolverCapabilities

    expected = sorted(
        [
            "name",
            "supports_binary",
            "supports_continuous",
            "supports_integer",
            "supports_multi_objective",
            "supports_quadratic",
            "supports_sensitivity",
            "supports_warm_start",
        ]
    )
    actual = sorted(f.name for f in dataclasses.fields(SolverCapabilities))

    assert actual == expected, (
        f"SolverCapabilities must have exactly these 8 fields: {expected}. Got: {actual}"
    )


@pytest.mark.unit
def test_capabilities_field_types() -> None:
    """SolverCapabilities.name must be str; all other fields must be bool."""
    from app.domains.solver.adapters.base import SolverCapabilities

    fields_by_name = {f.name: f for f in dataclasses.fields(SolverCapabilities)}

    name_field = fields_by_name["name"]
    # Accept both string annotation form and actual type object
    assert name_field.type in (str, "str"), (
        f"SolverCapabilities.name must have type str, got {name_field.type!r}"
    )

    bool_fields = [n for n in fields_by_name if n != "name"]
    for field_name in bool_fields:
        f = fields_by_name[field_name]
        assert f.type in (bool, "bool"), (
            f"SolverCapabilities.{field_name} must have type bool, got {f.type!r}"
        )


@pytest.mark.unit
def test_capabilities_equality() -> None:
    """Two SolverCapabilities instances with identical args must be equal and hash equal."""
    from app.domains.solver.adapters.base import SolverCapabilities

    kwargs = {
        "name": "scip",
        "supports_continuous": True,
        "supports_integer": True,
        "supports_binary": True,
        "supports_quadratic": True,
        "supports_sensitivity": True,
        "supports_warm_start": True,
        "supports_multi_objective": False,
    }
    caps_a = SolverCapabilities(**kwargs)
    caps_b = SolverCapabilities(**kwargs)

    assert caps_a == caps_b, "Identical SolverCapabilities instances must be equal"
    assert hash(caps_a) == hash(caps_b), (
        "Identical SolverCapabilities instances must hash to the same value"
    )
