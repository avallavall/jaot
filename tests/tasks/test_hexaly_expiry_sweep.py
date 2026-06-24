"""Phase 7.4 / HEX-09 — Celery beat sweep + Prometheus gauge.

Validation IDs: V-05 (gauge update), V-06 (fingerprint label).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_expiry_sweep_updates_gauge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V-05: hexaly_platform_license_expiry_impl reads .lic file and updates
    HEXALY_LICENSE_DAYS_REMAINING gauge with the actual days_remaining value.

    Reads the gauge back to confirm the side-effect — asserting only the
    return shape would silently regress if the gauge wiring were ever
    accidentally removed.
    """
    from app.shared.core.prometheus_metrics import HEXALY_LICENSE_DAYS_REMAINING
    from app.tasks.hexaly_platform_license_expiry import (
        hexaly_platform_license_expiry_impl,
    )

    lic = tmp_path / "hexaly.lic"
    lic.write_text("EXPIRES=2099-12-31\n")
    monkeypatch.setattr("app.tasks.hexaly_platform_license_expiry.LIC_PATH", lic)
    HEXALY_LICENSE_DAYS_REMAINING.clear()
    result = hexaly_platform_license_expiry_impl()
    assert result["days_remaining"] > 0
    assert result["fingerprint"] is not None
    # Gauge side-effect: the same value must land on the metric labelled
    # with this fingerprint (defends against silent un-wiring of the gauge).
    gauge_val = HEXALY_LICENSE_DAYS_REMAINING.labels(
        license_fingerprint=result["fingerprint"]
    )._value.get()
    assert gauge_val == result["days_remaining"]


def test_gauge_label_is_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V-06: gauge label is 'license_fingerprint' = first 8 chars of sha256.
    (Phase 7.4 / Plan 06 Task 1)"""
    from app.shared.core.prometheus_metrics import HEXALY_LICENSE_DAYS_REMAINING
    from app.tasks.hexaly_platform_license_expiry import (
        hexaly_platform_license_expiry_impl,
    )

    lic = tmp_path / "hexaly.lic"
    lic.write_text("EXPIRES=2099-12-31\nDATA1\n")
    monkeypatch.setattr("app.tasks.hexaly_platform_license_expiry.LIC_PATH", lic)
    HEXALY_LICENSE_DAYS_REMAINING.clear()
    result = hexaly_platform_license_expiry_impl()
    fp = result["fingerprint"]
    # The gauge must have been set under that label
    val = HEXALY_LICENSE_DAYS_REMAINING.labels(license_fingerprint=fp)._value.get()
    assert val > 0
