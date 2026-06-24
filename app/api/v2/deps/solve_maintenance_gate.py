"""Solve-only maintenance gate.

Returns HTTP 503 + ``Retry-After: 600`` when ``SOLVE_MAINTENANCE_MODE`` is on.
Orthogonal to ``MaintenanceMiddleware`` so admin/login/read routes stay up
during the drain window.
"""

import os
import time

from fastapi import HTTPException, status

from app.api.deps import DBSession
from app.services.platform_settings_service import PlatformSettingsService as PSS

# Short-TTL process cache: avoids a SELECT on every solve request for a flag
# that changes at most a few times per month. Up to _CACHE_TTL seconds of
# stale-false is acceptable — ``Retry-After: 600`` already expects clients
# to retry minutes later. Skipped under pytest so tests that toggle the flag
# rapidly see each change immediately (mirrors the rate_limiter.py pattern).
_CACHE_TTL = 5.0
_cache: dict[str, float | bool] = {"value": False, "expires_at": 0.0}


def _is_on(db: DBSession) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return PSS.get_bool(db, "SOLVE_MAINTENANCE_MODE", default=False)
    now = time.monotonic()
    if now < _cache["expires_at"]:
        return bool(_cache["value"])
    value = PSS.get_bool(db, "SOLVE_MAINTENANCE_MODE", default=False)
    _cache["value"] = value
    _cache["expires_at"] = now + _CACHE_TTL
    return value


def solve_maintenance_gate(db: DBSession) -> None:
    """Reject new solves while the ``SOLVE_MAINTENANCE_MODE`` flag is on."""
    if _is_on(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "solve_maintenance",
                "message": (
                    "Solve endpoints are temporarily unavailable for "
                    "maintenance. Please retry shortly."
                ),
            },
            headers={"Retry-After": "600"},
        )
