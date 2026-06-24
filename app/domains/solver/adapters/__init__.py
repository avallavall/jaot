"""Solver adapters — Protocol, Capabilities, Registry, concrete adapters.

Phase 4 / SOLV-01 / SOLV-02 / SOLV-03.

Public API:
    SolverAdapter — structural Protocol
    MultiObjectiveSolverAdapter — extended Protocol for native multi-obj
    SolverCapabilities — frozen dataclass
    SolverRegistry — singleton class
    registry — module-level instance
    register_default_adapters() — bootstrap, called from app/main.py
    SCIPAdapter — reference implementation
    SolverError / SolverNotFoundError / SolverUnavailableError — exceptions
"""

import logging

from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    MultiObjectiveSolverAdapter,
    SolverAdapter,
    SolverCapabilities,
    SolverError,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.adapters.highs import HiGHSAdapter
from app.domains.solver.adapters.registry import SolverRegistry, registry
from app.domains.solver.adapters.scip import SCIPAdapter

logger = logging.getLogger(__name__)


def register_default_adapters() -> None:
    """Register all built-in adapters with the singleton registry.

    Called exactly once from app.main.create_app() at startup, BEFORE any
    route registration. Idempotent — calling twice re-registers (last write
    wins) but does not raise.

    SCIP and HiGHS always register (their solvers ship in the base image).
    Hexaly is an optional proprietary extra: its SDK is NOT in
    requirements.txt (see requirements-hexaly.txt) and only the dedicated
    worker image installs it, so registration is gated on the SDK being
    importable. Even with the SDK present, the .lic file is mounted only
    on celery_worker_hexaly — on other processes the constructor's
    fail-fast (RuntimeError on missing /etc/jaot/hexaly.lic) is caught
    here so the process still starts. The listing endpoint
    /api/v2/solvers/available synthesises the hexaly entry from the
    worker-health probe when the adapter could not register locally, so
    the frontend dropdown still shows the multiplier badge.

    Also declares the specialized solver queues to the shared celery audit
    so workers running ``-Q solve_*`` are recognized as specialized and the
    producer-coverage check is skipped on their boot (the default worker
    keeps that responsibility). The reverse import — audit reaching into
    solver domain — would violate the app/shared boundary.
    """
    from app.domains.solver.queue_routing import SOLVER_QUEUE_MAP  # noqa: PLC0415
    from app.shared.core.celery_queue_audit import register_specialized_queues  # noqa: PLC0415

    register_specialized_queues(SOLVER_QUEUE_MAP.values())

    registry.register("scip", SCIPAdapter())
    registry.register("highs", HiGHSAdapter())

    from app.domains.solver.adapters.hexaly_availability import (  # noqa: PLC0415
        hexaly_available,
    )

    if hexaly_available():
        from app.domains.solver.adapters.hexaly import HexalyAdapter  # noqa: PLC0415

        try:
            registry.register("hexaly", HexalyAdapter())
        except RuntimeError as exc:
            # No /etc/jaot/hexaly.lic on this process (D-11 fail-fast). The
            # celery_worker_hexaly container has the .lic mounted and will
            # register normally; on the API container we tolerate the
            # missing file and skip registration. The /solvers/available
            # endpoint synthesises the hexaly entry on its own (Phase 7.4
            # HEX-08 fix).
            logger.warning("HexalyAdapter not registered on this process: %s", exc)


__all__ = [
    "DEFAULT_SOLVER_NAME",
    "HiGHSAdapter",
    "MultiObjectiveSolverAdapter",
    "SCIPAdapter",
    "SolverAdapter",
    "SolverCapabilities",
    "SolverError",
    "SolverNotFoundError",
    "SolverRegistry",
    "SolverUnavailableError",
    "register_default_adapters",
    "registry",
]
