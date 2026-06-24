"""Solver adapter contract — Protocol, Capabilities, and exceptions.

Phase 4 / SOLV-01 / SOLV-02 / SOLV-07.

This module defines the structural contract every solver adapter must
satisfy. It does NOT import pyscipopt — the Protocol is solver-agnostic by
design, and import-linter (Plan 02) enforces that property.

Design notes:
- Protocol over ABC per STATE.md decision (Protocol is duck-typing-native,
  no base class coupling for future third-party adapters).
- @dataclass(frozen=True) for SolverCapabilities per coding-style.md —
  capabilities are internal metadata, never mutated after registration.
- No @runtime_checkable on SolverAdapter: the registry is internal, mypy
  catches contract violations statically, and Python 3.12's stricter
  inspect.getattr_static() lookups make runtime checks slower than needed.
  See research §Pitfall 4.
- Protocol composition over optional methods per PEP 544: SCIPAdapter
  implements the base Protocol only; HiGHS/Hexaly (Phase 5/7) may opt into
  MultiObjectiveSolverAdapter by adding solve_multi_objective().
- Phase 7.4 / D-10: validate_license removed from Protocol. Hexaly's license is
  loaded at adapter __init__ time from /etc/jaot/hexaly.lic (platform license
  per D-01). The Protocol surface is now: capabilities + is_available + solve.
"""

from dataclasses import dataclass
from typing import Protocol

from app.schemas.optimization import (
    MultiObjectiveConfig,
    OptimizationProblem,
    OptimizationResult,
    ParetoPoint,
)


@dataclass(frozen=True)
class SolverCapabilities:
    """Describes what a solver can and can't do.

    Minimal per D-03. Phase 5 may extend this when wiring
    GET /api/v2/solvers/available — do NOT add fields here speculatively.

    Phase 7.4 / D-10: removed ``requires_license`` field. License validity
    is now a startup-time concern of the adapter (HexalyAdapter loads the
    platform license in __init__). Customer-facing pricing differentiation
    happens via PSS multipliers, not via this capability flag.
    """

    name: str
    supports_continuous: bool
    supports_integer: bool
    supports_binary: bool
    supports_quadratic: bool
    supports_sensitivity: bool
    supports_warm_start: bool
    supports_multi_objective: bool


class SolverError(Exception):
    """Base exception for solver adapter errors."""


class SolverNotFoundError(SolverError):
    """Raised when a solver name is not registered in the registry."""


class SolverUnavailableError(SolverError):
    """Raised when a registered solver is unavailable at runtime
    (missing binary, expired license, wrong version)."""


class SolverQueueMismatchError(SolverError):
    """Worker's ``SOLVER_QUEUE`` did not match the solver requested by the task."""


# Shared across adapters for strict inequality (< / >) conversion
STRICT_EPSILON = 1e-6

DEFAULT_SOLVER_NAME = "scip"
HEXALY_SOLVER_NAME = "hexaly"


class SolverAdapter(Protocol):
    """Structural contract for all solver adapters.

    Phase 7.4 / D-10: ``validate_license()`` removed. Hexaly's license is
    loaded at HexalyAdapter.__init__ (platform license per D-01). SCIP and
    HiGHS have no license concept.

    Not decorated with @runtime_checkable — see module docstring.
    """

    capabilities: SolverCapabilities

    def is_available(self) -> bool:
        """Return True if the solver can actually run on this machine."""
        ...

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
    ) -> OptimizationResult:
        """Solve a single-objective optimization problem.

        When capabilities.supports_sensitivity is True, the adapter
        populates result.sensitivity as part of its return value.
        When warm_start is provided and capabilities.supports_warm_start
        is True, the adapter sets result.warm_start_used.
        """
        ...


class MultiObjectiveSolverAdapter(SolverAdapter, Protocol):
    """Extends SolverAdapter with native multi-objective support.

    SCIPAdapter does NOT inherit this in Phase 4 — it sets
    supports_multi_objective = False and the orchestrator runs the
    weighted-sum / epsilon-constraint fallback by calling adapter.solve()
    on scalarized subproblems.

    HiGHSAdapter / HexalyAdapter in later phases MAY opt in by implementing
    this protocol and setting the capability flag True.
    """

    def solve_multi_objective(
        self,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
    ) -> list[ParetoPoint]:
        """Native multi-objective solve. Returns Pareto front."""
        ...
