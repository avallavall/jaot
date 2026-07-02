"""JModel DSL feature gate.

Returns HTTP 404 when the ``JAOT_DSL`` flag is off, so the compile endpoint is
invisible unless an operator turns the feature on (it ships dark). Mirrors the
short-TTL process cache of ``solve_maintenance_gate`` — the flag changes at most a
few times ever, and per-keystroke compiles should not each hit the DB.
"""

import os
import time

from fastapi import HTTPException, status

from app.api.deps import DBSession
from app.services.platform_settings_service import PlatformSettingsService as PSS

_CACHE_TTL = 5.0
_cache: dict[str, float | bool] = {"value": False, "expires_at": 0.0}


def dsl_enabled(db: DBSession) -> bool:
    """Fresh read of the ``JAOT_DSL`` flag (used by the status endpoint)."""
    return PSS.get_bool(db, "JAOT_DSL", default=False)


def _is_on(db: DBSession) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return PSS.get_bool(db, "JAOT_DSL", default=False)
    now = time.monotonic()
    if now < _cache["expires_at"]:
        return bool(_cache["value"])
    value = PSS.get_bool(db, "JAOT_DSL", default=False)
    _cache["value"] = value
    _cache["expires_at"] = now + _CACHE_TTL
    return value


def dsl_feature_gate(db: DBSession) -> None:
    """Reject DSL requests with 404 while ``JAOT_DSL`` is off."""
    if not _is_on(db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "dsl_disabled",
                "message": "The JModel DSL feature is not enabled on this instance.",
            },
        )
