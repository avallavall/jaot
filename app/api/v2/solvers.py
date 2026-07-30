"""Solver management endpoints — Phase 7.4 / D-06 / D-11.

Phase 7.4 ripped the BYOL license surface (POST /validate-license, GET
/licenses, DELETE /licenses/{solver}) per D-06. Only ``GET /available``
remains. The response shape includes:

- ``available``: bool — real-time Hexaly worker health (D-11). SCIP and HiGHS
  always True (those workers run from the base image and never crash on
  license).
- ``reason`` + ``retry_after``: present only when ``available=False`` (D-11).
- ``capabilities``: what the solver can actually deliver (v3.2). Until this
  landed, ``SolverCapabilities`` had NO consumer outside the adapters
  themselves: the UI offered the same analysis surface for every solver, so a
  Hexaly run advertised shadow prices Hexaly does not compute and a Live Solve
  that never streams. See :func:`_capabilities_payload` for what is exposed
  and — just as deliberately — what is not.

The ``requires_license`` field is gone (D-10) — Hexaly is available to every
user. Per-solver credit multipliers died with the credit system (ADR-008).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.deps import (  # OrgOwnerUser intentionally omitted (W7 fix — Branch A: no surviving callers in app/api/v2/ outside solvers.py)
    CurrentUser,
    DBSession,
)
from app.domains.solver.adapters import registry
from app.domains.solver.adapters.base import HEXALY_SOLVER_NAME, SolverCapabilities
from app.domains.solver.services import worker_health as _worker_health
from app.schemas.solver import (
    AvailableSolver,
    AvailableSolversResponse,
    SolverCapabilityFlags,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/solvers", tags=["solvers"])

# Fixed per-solver descriptions (D-03 from 05-CONTEXT.md): description is a
# short fixed string, not derived from capabilities.
_SOLVER_DESCRIPTIONS: dict[str, str] = {
    "scip": "Academic MIP solver",
    "highs": "Fast open-source LP/MIP",
    "hexaly": "Commercial solver for quadratic / non-convex problems",
}


def _capabilities_payload(caps: SolverCapabilities) -> SolverCapabilityFlags:
    """Project ``SolverCapabilities`` onto the flags the UI can act on.

    Only flags with an *observable consequence for the user* are exposed, so a
    section can decline itself with a reason instead of rendering empty:

    - ``sensitivity`` — shadow prices / reduced costs (the Sensitivity tab, and
      the LP section demoted inside the exact-analysis panel).
    - ``warm_start`` — whether a re-solve can be seeded from the incumbent
      (the what-if relax runs).
    - ``quadratic`` — whether a model carrying quadratic terms can run at all.
    - ``progress`` — per-incumbent streaming (Live Solve).

    ``supports_multi_objective`` is deliberately NOT exposed: it flags *native*
    support, and the orchestrator gives every solver multi-objective through
    scalarization. Surfacing the raw flag would tell the user "this solver
    cannot do multi-objective" about a solver that demonstrably can — the exact
    class of half-truth this endpoint exists to remove.

    ``supports_continuous`` / ``_integer`` / ``_binary`` are True on every
    adapter today and carry no decision for the user, so they stay internal.
    """
    return SolverCapabilityFlags(
        sensitivity=caps.supports_sensitivity,
        warm_start=caps.supports_warm_start,
        quadratic=caps.supports_quadratic,
        progress=caps.supports_progress,
    )


def _hexaly_capabilities() -> SolverCapabilities | None:
    """Hexaly's declared capabilities WITHOUT constructing the adapter.

    ``hexaly.py`` imports the proprietary SDK lazily (only inside
    ``is_available()`` / ``solve()``) and ``capabilities`` is a class
    attribute, so reading it needs neither the SDK nor the ``/etc/jaot/hexaly.lic``
    that ``__init__`` fail-fasts on. That keeps the synthesised listing entry on
    the SAME single source of truth as the real adapter instead of duplicating
    the flags in this module, where they would silently rot.
    """
    try:
        from app.domains.solver.adapters.hexaly import HexalyAdapter  # noqa: PLC0415

        return HexalyAdapter.capabilities
    except Exception:  # pragma: no cover - defensive: module must stay importable
        logger.warning("Could not read HexalyAdapter.capabilities", exc_info=True)
        return None


@router.get(
    "/available",
    response_model=AvailableSolversResponse,
    # Absent, not null: a solver whose capabilities could not be read must carry
    # NO ``capabilities`` key, so the consumer falls back to claiming nothing
    # instead of reading a fabricated one. Same for ``reason``/``retry_after``,
    # which only ride an unavailable solver.
    response_model_exclude_none=True,
    operation_id="list_available_solvers",
)
def list_available_solvers(user: CurrentUser, db: DBSession) -> AvailableSolversResponse:
    """Return solvers available on this server with real-time availability.

    D-11: SCIP and HiGHS are always ``available=True`` (in-image solvers);
    Hexaly reflects ``_probe_hexaly_worker()`` — when the
    celery_worker_hexaly container is unhealthy or down, ``available=False``
    with ``reason="maintenance"`` so the frontend can grey out the option.

    Each entry also carries ``capabilities`` (v3.2). This listing is the single
    place the frontend learns what a solver can deliver, including for an
    execution that ALREADY ran: the analysis panels look the run's solver up by
    name here. A solver that is no longer listed yields no capabilities, and
    every consumer must fall back to claiming nothing rather than guessing.
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
    # renders the "maintenance" greyed-out state.
    from app.domains.solver.adapters.hexaly_availability import (  # noqa: PLC0415
        hexaly_available,
    )

    # Carry the capabilities alongside the name: the synthesised hexaly entry
    # must describe the same solver the worker will actually run. Capabilities
    # are OPTIONAL per entry — a solver that is listable must stay listable even
    # if its declared capabilities cannot be read, so listing never regresses
    # into hiding a solver the user can legitimately pick.
    listed: list[tuple[str, SolverCapabilities | None]] = [
        (cap.name, cap) for cap in available_caps
    ]
    if HEXALY_SOLVER_NAME not in registered_names and (hexaly_worker_healthy or hexaly_available()):
        listed.append((HEXALY_SOLVER_NAME, _hexaly_capabilities()))

    solvers: list[AvailableSolver] = []
    for name, caps in listed:
        entry = AvailableSolver(
            name=name,
            available=True,
            description=_SOLVER_DESCRIPTIONS.get(name, name),
            capabilities=_capabilities_payload(caps) if caps is not None else None,
        )
        if name == HEXALY_SOLVER_NAME and not hexaly_worker_healthy:
            entry.available = False
            entry.reason = "maintenance"
            entry.retry_after = None
        solvers.append(entry)

    logger.debug(
        "list_available_solvers: %d solvers (hexaly_worker_healthy=%s)",
        len(solvers),
        hexaly_worker_healthy,
    )
    return AvailableSolversResponse(solvers=solvers)
