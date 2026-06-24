"""Phase 7.4 / HEX-08 — platform license loader contract.

Validation IDs: V-01 (load), V-02 (missing fail-fast), V-03 (expired fail-fast).

The ``make_lic_file`` factory fixture lives in
``tests/unit/domains/solver/conftest.py`` and is shared with the adapter
contract tests (``adapters/test_hexaly_adapter.py``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest


def test_platform_license_load(
    make_lic_file: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """V-01: HexalyAdapter.__init__ loads /etc/jaot/hexaly.lic and exposes
    fingerprint + expires_at matching the file content."""
    from app.domains.solver.adapters.hexaly import HexalyAdapter

    lic = make_lic_file(expires="2099-12-31")
    monkeypatch.setattr("app.domains.solver.adapters.hexaly.HEXALY_LIC_PATH", lic)
    adapter = HexalyAdapter()
    expected_fingerprint = hashlib.sha256(lic.read_bytes()).hexdigest()[:8]
    assert adapter._license_fingerprint == expected_fingerprint
    assert adapter._license_expires_at is not None
    assert adapter._license_expires_at.year == 2099
    assert adapter._license_expires_at.month == 12
    assert adapter._license_expires_at.day == 31


def test_missing_license_fails_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V-02: missing .lic file raises RuntimeError at HexalyAdapter() construction.
    (Phase 7.4 / Plan 02 Task 2)"""
    from app.domains.solver.adapters.hexaly import HexalyAdapter

    monkeypatch.setattr(
        "app.domains.solver.adapters.hexaly.HEXALY_LIC_PATH",
        tmp_path / "does-not-exist.lic",
    )
    with pytest.raises(RuntimeError, match="Platform Hexaly license"):
        HexalyAdapter()


def test_expired_license_fails_fast(
    make_lic_file: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """V-03: expired .lic causes worker fail-fast at HexalyAdapter()."""
    from app.domains.solver.adapters.hexaly import HexalyAdapter

    lic = make_lic_file(expires="2000-01-01")
    monkeypatch.setattr("app.domains.solver.adapters.hexaly.HEXALY_LIC_PATH", lic)
    with pytest.raises(RuntimeError, match="expired"):
        HexalyAdapter()
