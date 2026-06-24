"""Solver registry — singleton mapping solver name to adapter instance.

Phase 4 / SOLV-03. See research §Registry Concurrency for the thread-safety
rationale: SolverRegistry is a module-level singleton. Thread safety is
achieved by:
  1. Registration happens exactly once per process in
     register_default_adapters(), called at app startup BEFORE any request
     handler runs.
  2. After startup, _adapters is read-only — dict.get() is atomic under
     CPython's GIL.
  3. Celery workers are separate processes (prefork pool), so each has its
     own registry state. No cross-worker shared memory.
  4. reset() is test-only and tests run in a single process.
If the deploy model ever adds post-startup mutation (hot-reload, runtime
adapter registration via admin API), revisit with threading.Lock.
"""

import logging

from app.domains.solver.adapters.base import (
    SolverAdapter,
    SolverCapabilities,
    SolverNotFoundError,
    SolverUnavailableError,
)

logger = logging.getLogger(__name__)


class SolverRegistry:
    """In-memory registry of solver adapters.

    D-10 / D-11: adapters always register, `list_available()` filters via
    `is_available()`, `get()` raises when unavailable.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, SolverAdapter] = {}

    def register(self, name: str, adapter: SolverAdapter) -> None:
        """Register an adapter under its canonical lowercase name."""
        self._adapters[name.lower()] = adapter

    def get(self, name: str) -> SolverAdapter:
        """Return the adapter for `name`.

        Raises:
            SolverNotFoundError: not registered.
            SolverUnavailableError: registered but is_available() is False.
        """
        key = name.lower()
        if key not in self._adapters:
            # WR-03 anti-oracle: do NOT include the registered-names list
            # in the exception message. It propagates to the HTTP 422 body
            # via `detail=str(exc)` on the synchronous /solve path and
            # would enumerate available solvers to unauthenticated callers.
            logger.debug(
                "Solver %r not registered. Available: %s",
                name,
                sorted(self._adapters.keys()),
            )
            raise SolverNotFoundError(f"Solver '{name}' is not registered.")
        adapter = self._adapters[key]
        if not adapter.is_available():
            raise SolverUnavailableError(
                f"Solver '{name}' is registered but not available at runtime."
            )
        return adapter

    def list_available(self) -> list[SolverCapabilities]:
        """Return capabilities of every registered adapter that is available."""
        return [a.capabilities for a in self._adapters.values() if a.is_available()]

    def reset(self) -> None:
        """Clear the registry. Used by pytest fixtures for test isolation."""
        self._adapters.clear()


# Module-level singleton — one instance per process.
registry = SolverRegistry()
