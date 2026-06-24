"""Shim: re-exports from app.domains.solver.adapters._scip_import.

Phase 4 Plan 03 / D-07 — file_import absorbed into SCIP adapter. This shim
preserves the old import path so existing callers (tests/test_file_import.py,
Phase 3 re-export chain from app/services/solver/file_import.py, solve_orchestrator
imports) continue to work unchanged.

Uses lazy __getattr__ instead of sys.modules replacement so the shim survives
importlib.reload() and sys.modules.pop() patterns used in isolation tests.
"""

from __future__ import annotations


def __getattr__(name: str) -> object:
    from app.domains.solver.adapters import _scip_import as _real

    return getattr(_real, name)
