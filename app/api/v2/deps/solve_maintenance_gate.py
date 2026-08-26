"""Solve-only maintenance gate.

Returns HTTP 503 + ``Retry-After: 600`` when ``SOLVE_MAINTENANCE_MODE`` is on.
Orthogonal to ``MaintenanceMiddleware`` so admin/login/read routes stay up
during the drain window.
"""

from fastapi import HTTPException, status

from app.api.deps import DBSession
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.ttl_probe import TTLProbe

# Short-TTL process cache: avoids a SELECT on every solve request for a flag
# that changes at most a few times per month. Up to _CACHE_TTL seconds of
# stale-false is acceptable — ``Retry-After: 600`` already expects clients
# to retry minutes later.
#
# ``refresh_anyway``: this runs as a FastAPI dependency, and the read is one
# indexed SELECT. A caller that blocked on a lock here would hold up the
# request it is gating for no gain; a handful of concurrent reads on an expired
# value costs less than that.
#
# This used to be its own dict-and-timestamp cache, and it used to skip itself
# entirely when PYTEST_CURRENT_TEST was set — so the cached path, the only path
# production takes, was never once exercised by a test. The shared probe is
# cleared between tests by an autouse fixture instead.
_CACHE_TTL = 5.0
_gate_probe = TTLProbe[bool](ttl_seconds=_CACHE_TTL, on_contention="refresh_anyway")


def _is_on(db: DBSession) -> bool:
    return _gate_probe.get(lambda: PSS.get_bool(db, "SOLVE_MAINTENANCE_MODE", default=False))


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
