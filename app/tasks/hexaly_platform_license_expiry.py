"""Daily Celery Beat task — read platform Hexaly .lic and update Prometheus gauge.

Phase 7.4 / D-07 / HEX-09:
- Updates the ``HEXALY_LICENSE_DAYS_REMAINING`` Prometheus gauge (label =
  ``license_fingerprint``) so Alertmanager + Grafana can page on imminent
  expiry.
- Sets the gauge to ``-1`` when the .lic file is missing or the expiry line
  cannot be parsed (RESEARCH Area 5 spec — sentinel for "unknown / unparseable").

Implementation split (mirrors ``app/tasks/license_tasks.py`` pattern):
- ``hexaly_platform_license_expiry_impl()``: pure function, no Celery context,
  no DB. Tests invoke directly (no Session needed because the task reads a
  filesystem path, not a DB row).
- ``hexaly_platform_license_expiry_sweep``: thin ``@celery_app.task`` wrapper
  that calls the impl + logs the summary.

Replaces the deleted ``app/tasks/license_tasks.py`` (Plan 09).
"""

from __future__ import annotations

import logging
from typing import Any

from app.domains.solver.adapters._license_utils import (
    extract_expires_at,
    fingerprint,
)
from app.domains.solver.adapters.hexaly import HEXALY_LIC_PATH as LIC_PATH
from app.shared.core.celery_app import celery_app
from app.shared.core.prometheus_metrics import HEXALY_LICENSE_DAYS_REMAINING
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

# Sentinel value for "unknown" days remaining — Grafana shows as red bar,
# Alertmanager rule treats < 30 as warning so -1 also fires (intentional).
_UNKNOWN_DAYS_SENTINEL = -1


def hexaly_platform_license_expiry_impl() -> dict[str, Any]:
    """Read ``LIC_PATH`` and update HEXALY_LICENSE_DAYS_REMAINING.

    Returns:
        Summary dict with keys:
          - ``days_remaining``: int — days until expiry, or ``-1`` when unknown
          - ``fingerprint``: str | None — sha256[:8] of the .lic plaintext, or
            ``None`` when the file is missing
    """
    # Reset gauge labels every run — operator-rotated licenses drop their
    # previous fingerprint to 0, preventing stale alerts from firing forever.
    try:
        HEXALY_LICENSE_DAYS_REMAINING.clear()
    except Exception as exc:  # pragma: no cover - prometheus_client is stable
        logger.warning("Could not clear HEXALY_LICENSE_DAYS_REMAINING: %s", exc)

    if not LIC_PATH.exists():
        logger.warning(
            "hexaly_platform_license_expiry: %s not found — emitting -1 sentinel.",
            LIC_PATH,
        )
        # Use a stable label so Alertmanager has a consistent target;
        # "missing" is a reserved fingerprint value.
        HEXALY_LICENSE_DAYS_REMAINING.labels(license_fingerprint="missing").set(
            _UNKNOWN_DAYS_SENTINEL
        )
        return {"days_remaining": _UNKNOWN_DAYS_SENTINEL, "fingerprint": None}

    plaintext_bytes = LIC_PATH.read_bytes()
    fp = fingerprint(plaintext_bytes)
    expires_at = extract_expires_at(plaintext_bytes)

    if expires_at is None:
        logger.warning(
            "hexaly_platform_license_expiry: could not parse expiry from %s "
            "(fingerprint=%s) — emitting -1 sentinel.",
            LIC_PATH,
            fp,
        )
        HEXALY_LICENSE_DAYS_REMAINING.labels(license_fingerprint=fp).set(_UNKNOWN_DAYS_SENTINEL)
        return {"days_remaining": _UNKNOWN_DAYS_SENTINEL, "fingerprint": fp}

    days_remaining = (expires_at - utcnow()).days
    HEXALY_LICENSE_DAYS_REMAINING.labels(license_fingerprint=fp).set(days_remaining)
    logger.info(
        "hexaly_platform_license_expiry: fingerprint=%s expires_at=%s days_remaining=%d",
        fp,
        expires_at.isoformat(),
        days_remaining,
    )
    return {"days_remaining": days_remaining, "fingerprint": fp}


@celery_app.task(
    bind=True,
    name="hexaly_platform_license_expiry_sweep",
    acks_late=True,
)
def hexaly_platform_license_expiry_sweep(self: Any) -> dict[str, Any]:
    """Thin Celery wrapper — invokes the pure impl and returns the summary."""
    try:
        return hexaly_platform_license_expiry_impl()
    except Exception:
        logger.exception("hexaly_platform_license_expiry_sweep failed")
        raise


__all__ = [
    "LIC_PATH",
    "hexaly_platform_license_expiry_impl",
    "hexaly_platform_license_expiry_sweep",
]
