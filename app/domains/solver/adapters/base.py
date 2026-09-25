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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.schemas.optimization import (
    MultiObjectiveConfig,
    OptimizationProblem,
    OptimizationResult,
    ParetoPoint,
    ProgressPoint,
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
    # Live Solve: the adapter can stream per-incumbent progress through the
    # ``on_progress`` callback of ``solve()``. Default False (keeps every existing
    # instantiation valid); SCIP and JAOS set it True.
    supports_progress: bool = False


class SolverError(Exception):
    """Base exception for solver adapter errors."""


class SolverNotFoundError(SolverError):
    """Raised when a solver name is not registered in the registry."""


class SolverUnavailableError(SolverError):
    """Raised when a registered solver is unavailable at runtime
    (missing binary, expired license, wrong version)."""


class SolverQueueMismatchError(SolverError):
    """Worker's ``SOLVER_QUEUE`` did not match the solver requested by the task."""


# Codes a linear-only solver puts on its refusal of a quadratic model. The page
# shows the translated sentence for the code. ``error_message`` keeps the English
# sentence, because API clients read it and the page falls back to it. Every code
# here needs an ``errors.codes`` entry in frontend/messages/en.json (a test checks).
CODE_LINEAR_ONLY = "solver.linear_only"
CODE_QUADRATIC_IN_OBJECTIVE = "solver.quadratic_in_objective"
CODE_QUADRATIC_IN_CONSTRAINT = "solver.quadratic_in_constraint"
LINEAR_ONLY_CODES = frozenset(
    {CODE_LINEAR_ONLY, CODE_QUADRATIC_IN_OBJECTIVE, CODE_QUADRATIC_IN_CONSTRAINT}
)


class LinearOnlyError(SolverError, ValueError):
    """A linear-only solver refusing a quadratic model.

    It carries a code and plain-value params so the refusal can be shown in the
    reader's language. It is a ``ValueError`` too: the JAOS adapter turns a
    ``ValueError`` raised while it builds the model into an error result, and
    this refusal must stay one of those.
    """

    def __init__(self, message: str, *, code: str, params: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.params = params


def quadratic_term_refusal(
    message: str, *, solver: str, variables: list[str], constraint: str | None
) -> LinearOnlyError:
    """The refusal of one quadratic term, in the objective or in a named constraint."""
    params = {"solver": solver, "term": "*".join(variables)}
    if constraint is None:
        return LinearOnlyError(message, code=CODE_QUADRATIC_IN_OBJECTIVE, params=params)
    return LinearOnlyError(
        message,
        code=CODE_QUADRATIC_IN_CONSTRAINT,
        params={**params, "constraint": constraint},
    )


def refusal_fields(exc: BaseException) -> dict[str, Any]:
    """``error_code`` and ``error_params`` for an error result built from ``exc``.

    Empty for any other exception. A code promises a known sentence, and an
    unexpected failure has none: the page shows its English message as it is.
    """
    if isinstance(exc, LinearOnlyError):
        return {"error_code": exc.code, "error_params": dict(exc.params)}
    return {}


#: "The version has not been read yet." Not None, because None is a legitimate
#: answer — the solver is there and would not say — and caching it must stop the
#: adapter from asking again on every call.
UNREAD_VERSION: Any = object()


class CachedVersion:
    """Ask the solver its version once per process, however it is asked.

    The six adapters read a version in different ways. Three query a Python
    binding, two start a child process, and one reads package metadata. They all
    cache it the same way. When that was written out in each adapter, Hexaly
    did not cache it and re-read the version on every solver listing.

    The default lives on the class, so an adapter opts in by inheriting and
    implementing :meth:`_read_version`; nothing has to be remembered in
    ``__init__``. Assignment in :meth:`version` creates an instance attribute,
    so the shared default is read but never mutated.
    """

    _version: str | None | Any = UNREAD_VERSION

    def version(self) -> str | None:
        """The solver's version string, or None when it will not say."""
        if self._version is UNREAD_VERSION:
            self._version = self._read_version()
        return self._version

    def _read_version(self) -> str | None:
        """Ask this particular solver. Must never raise: a version is a label on
        a stored table, and failing to read one cannot be allowed to stop a
        solve or fail a request."""
        raise NotImplementedError


# Shared across adapters for strict inequality (< / >) conversion
STRICT_EPSILON = 1e-6


def binary_bounds(lower: float | None, upper: float | None) -> tuple[float, float]:
    """The bounds of a binary variable: its own bounds, kept inside [0, 1].

    Validation accepts ``{"type": "binary", "upper_bound": 0}``, which is how a
    caller closes a plant or forbids an arc. Every adapter built binaries as a
    plain 0/1 and dropped those bounds, so the solve returned the forbidden 1
    and called the answer optimal.
    """
    lb = 0.0 if lower is None else max(0.0, float(lower))
    ub = 1.0 if upper is None else min(1.0, float(upper))
    return lb, ub


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

    def version(self) -> str | None:
        """The solver's own version string, or None when it cannot be read.

        Recorded alongside a solver comparison so a stored table can still be
        explained after the images have been rebuilt. Seconds measured against
        CBC 2.10.12 say nothing about CBC 2.11, and a table with no version on
        it cannot tell you which one it timed.

        Cheap to call repeatedly: every adapter caches the answer for the life
        of the process. A version does not change under a running process, and
        two of these adapters have to start a child process to find out.
        """
        ...

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> OptimizationResult:
        """Solve a single-objective optimization problem.

        When capabilities.supports_sensitivity is True, the adapter
        populates result.sensitivity as part of its return value.
        When warm_start is provided and capabilities.supports_warm_start
        is True, the adapter sets result.warm_start_used.

        ``on_progress``, when provided and capabilities.supports_progress is
        True, is invoked with a ``ProgressPoint`` on each new incumbent during
        the solve (used by Live Solve to stream convergence). It is best-effort:
        adapters that do not support it accept and ignore the argument, and a
        callback that raises must never abort the solve.
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
