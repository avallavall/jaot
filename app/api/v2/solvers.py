"""Solver management endpoints — Phase 7.4 / D-06 / D-11 / D-12.

Phase 7.4 ripped the BYOL license surface (POST /validate-license, GET
/licenses, DELETE /licenses/{solver}) per D-06. Only ``GET /available``
remains. The response shape now includes:

- ``available``: bool — real-time Hexaly worker health (D-11). SCIP and HiGHS
  always True (those workers run from the base image and never crash on
  license).
- ``multiplier``: float — per-solver credit multiplier from PSS
  ``pricing.solver_multiplier.<name>`` (D-12 / PRC-01). Defaults 1.0/1.2/5.0.
- ``reason`` + ``retry_after``: present only when ``available=False`` (D-11).

The ``requires_license`` field is gone (D-10) — Hexaly is available to every
customer; pricing is differentiated by ``multiplier``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.api.deps import (  # OrgOwnerUser intentionally omitted (W7 fix — Branch A: no surviving callers in app/api/v2/ outside solvers.py)
    CurrentUser,
    DBSession,
)
from app.domains.solver.adapters import registry
from app.domains.solver.adapters.base import HEXALY_SOLVER_NAME
from app.domains.solver.services import worker_health as _worker_health
from app.services.platform_settings_service import PlatformSettingsService as PSS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/solvers", tags=["solvers"])

# Fixed per-solver descriptions (D-03 from 05-CONTEXT.md): description is a
# short fixed string, not derived from capabilities.
_SOLVER_DESCRIPTIONS: dict[str, str] = {
    "scip": "Academic MIP solver",
    "highs": "Fast open-source LP/MIP",
    "hexaly": "Commercial solver for quadratic / non-convex problems",
}

_DEFAULT_MULTIPLIER = 1.0


@router.get("/available", operation_id="list_available_solvers")
def list_available_solvers(user: CurrentUser, db: DBSession) -> dict[str, Any]:
    """Return solvers available on this server with multiplier + availability.

    Phase 7.4 / D-11 / D-12: response includes per-solver credit multiplier
    (from PSS ``pricing.solver_multiplier.<name>``) and real-time Hexaly
    worker health. SCIP and HiGHS are always ``available=True`` (in-image
    solvers); Hexaly reflects ``_probe_hexaly_worker()`` — when the
    celery_worker_hexaly container is unhealthy or down, ``available=False``
    with ``reason="maintenance"`` so the frontend can grey out the option.
    """
    available_caps = registry.list_available()
    registered_names = {cap.name for cap in available_caps}

    # Probe hexaly worker once per request — TTL cache lives inside worker_health.
    # Import via module reference so monkeypatch in tests works correctly.
    hexaly_worker_healthy, _hexaly_msg = _worker_health._probe_hexaly_worker()

    # Surface hexaly even when the API process did not register the adapter.
    # The SDK is an optional extra that only ships in the dedicated worker
    # image (requirements-hexaly.txt), and the .lic is mounted only on
    # celery_worker_hexaly — so on the API process the adapter is normally
    # absent from registry.list_available(). Inject a synthetic entry when a
    # real Hexaly worker is consuming the queue (probe) or the SDK happens to
    # be importable locally (dev all-in-one), so the frontend dropdown still
    # renders the multiplier badge and the "maintenance" greyed-out state.
    from app.domains.solver.adapters.hexaly_availability import (  # noqa: PLC0415
        hexaly_available,
    )

    listed_names: list[str] = [cap.name for cap in available_caps]
    if HEXALY_SOLVER_NAME not in registered_names and (hexaly_worker_healthy or hexaly_available()):
        listed_names.append(HEXALY_SOLVER_NAME)

    # Single-query batch lookup of all per-solver multiplier settings.
    # PSS.get_many returns a dict {key: value_str} backed by one DB round-trip
    # plus a registry-default fallback for keys absent from the DB — replaces
    # the per-solver get_float loop (was N reads, now 1).
    multiplier_keys = [f"pricing.solver_multiplier.{name}" for name in listed_names]
    raw_multipliers = PSS.get_many(db, multiplier_keys)

    solvers: list[dict[str, Any]] = []
    for name in listed_names:
        raw = raw_multipliers.get(f"pricing.solver_multiplier.{name}")
        try:
            multiplier = float(raw) if raw is not None else _DEFAULT_MULTIPLIER
        except (TypeError, ValueError):
            multiplier = _DEFAULT_MULTIPLIER
        entry: dict[str, Any] = {
            "name": name,
            "available": True,
            "description": _SOLVER_DESCRIPTIONS.get(name, name),
            "multiplier": multiplier,
        }
        if name == HEXALY_SOLVER_NAME and not hexaly_worker_healthy:
            entry["available"] = False
            entry["reason"] = "maintenance"
            entry["retry_after"] = None
        solvers.append(entry)

    logger.debug(
        "list_available_solvers: %d solvers (hexaly_worker_healthy=%s)",
        len(solvers),
        hexaly_worker_healthy,
    )
    return {"solvers": solvers}
