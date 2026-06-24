"""Shim: re-exports from app.domains.solver.adapters._scip_model_builder.

Phase 4 Plan 03 / D-07 — model_builder absorbed into SCIP adapter. This shim
preserves the old import path so existing callers (file_export.py old
imports, tests/test_file_export.py indirect, Phase 3 re-export chain from
app/services/solver/model_builder.py) continue to work unchanged.

Uses lazy __getattr__ instead of sys.modules replacement so the shim survives
importlib.reload() and sys.modules.pop() patterns used in isolation tests.
"""

from __future__ import annotations


def __getattr__(name: str) -> object:
    from app.domains.solver.adapters import _scip_model_builder as _real

    return getattr(_real, name)
