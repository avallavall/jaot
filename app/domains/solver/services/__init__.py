"""Solver-domain services package.

Imports are lazy via ``__getattr__`` so that importing a sibling submodule
(e.g. ``expression_parser``) does NOT pull in ``solver_service`` and its
dependency graph. Direct imports of ``SolverService`` /
``get_solver_service`` resolve through the lazy hook below — this keeps the
package surface stable while letting individual submodules stay
import-cheap.
"""

from __future__ import annotations

from app.domains.solver.services.expression_parser import ExpressionParser

__all__ = ["SolverService", "get_solver_service", "ExpressionParser", "compute_iis"]


def __getattr__(name: str) -> object:
    """Lazy-import SolverService and get_solver_service to avoid eager pyscipopt import."""
    if name in ("SolverService", "get_solver_service"):
        from app.domains.solver.services.solver_service import (  # noqa: PLC0415
            SolverService,
            get_solver_service,
        )

        return {"SolverService": SolverService, "get_solver_service": get_solver_service}[name]
    if name == "compute_iis":
        from app.domains.solver.services.infeasibility import compute_iis  # noqa: PLC0415

        return compute_iis
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
