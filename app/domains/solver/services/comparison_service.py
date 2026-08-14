"""Planning for a solver comparison: who runs, who cannot, and on what terms.

Everything here is pure. It decides two things and persists nothing:

1. **The terms.** Every solver in a comparison must receive the same time limit,
   the same gap tolerance and the same thread count, or the table is comparing
   settings instead of solvers. :func:`build_comparison_problem` stamps them onto
   one problem, and that single object is what every column solves.

2. **Who can run at all.** A solver that cannot express the model must say so,
   not fail with a parse error halfway down the table. :func:`plan_comparison`
   asks each adapter's declared capabilities against the problem's class and
   returns a reason code for the ones that have to sit the run out.

The class comes from :func:`app.domains.solver.services.classify.classify`, which
is the single source of truth the auto-router also uses. Re-deriving "is this
integer" here is exactly the contract drift that module exists to prevent.

No HTTPException is raised in this file. The domain reports reason codes; the API
layer decides which of them is a 4xx and what the message says.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.solver.adapters import registry
from app.domains.solver.adapters.base import (
    SolverCapabilities,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.services.classify import (
    QUADRATIC_CLASSES,
    ProblemClass,
    classify,
)
from app.schemas.optimization import OptimizationProblem

#: Written to ``ModelExecution.solver_status`` for a solver that never ran because
#: it cannot express the model. The row's ``status`` is "failed" (no solution was
#: produced), but this value is what the UI reads to render "not supported"
#: instead of an error. A blank cell would be read as zero.
UNSUPPORTED_SOLVER_STATUS = "unsupported"

#: Why a solver is sitting a comparison out. Machine-readable on purpose — the
#: sentence the user reads is translated in the frontend, not stored here.
REASON_INTEGER_VARIABLES = "integer_variables"
REASON_QUADRATIC_TERMS = "quadratic_terms"
REASON_NOT_REGISTERED = "not_registered"
REASON_NOT_AVAILABLE = "not_available"

#: Solvers that can never take part, whatever the model is, with the reason.
#:
#: Hexaly needs its SDK and its licence file, and both exist only on the Hexaly
#: worker image. The comparison worker runs the base image so that one machine
#: times every solver, and those two requirements cannot both be true at once.
#: Naming it here (rather than letting the registry lookup fail) is what lets the
#: UI explain the absence instead of showing a solver that mysteriously never
#: appears.
PERMANENTLY_EXCLUDED: dict[str, str] = {
    "hexaly": REASON_NOT_AVAILABLE,
}


@dataclass(frozen=True)
class SolverPlanEntry:
    """One column of the comparison, decided before anything is queued."""

    solver_name: str
    #: None means it will run. Otherwise a REASON_* code and it will not.
    unsupported_reason: str | None

    @property
    def will_run(self) -> bool:
        return self.unsupported_reason is None


def normalize_solver_names(requested: list[str]) -> list[str]:
    """Lowercase, strip and de-duplicate while keeping the caller's order.

    Order is kept because it is the order the solvers run in, and a comparison
    that reordered its own columns between the request and the result would be
    confusing for no gain.
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw in requested:
        name = raw.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def build_comparison_problem(
    problem: OptimizationProblem,
    *,
    time_limit_seconds: float,
    gap_tolerance: float,
    threads: int,
) -> OptimizationProblem:
    """Return a copy of ``problem`` carrying the settings every solver will get.

    A copy, not a mutation: the caller's problem is left untouched per the
    project immutability rule, and the returned object is the exact snapshot
    stored on the comparison row.

    ``verbose`` is forced off. Solver chatter costs time, and one solver logging
    while another does not would show up in the seconds column.

    ``solver_name`` is cleared. A problem that names its own solver would make
    every column run the same one; the comparison chooses per column instead.
    """
    return problem.model_copy(
        update={
            "solver_name": None,
            "options": problem.options.model_copy(
                update={
                    "time_limit_seconds": time_limit_seconds,
                    "gap_tolerance": gap_tolerance,
                    "threads": threads,
                    "verbose": False,
                }
            ),
        }
    )


def _capability_reason(caps: SolverCapabilities, problem_class: ProblemClass) -> str | None:
    """Why these capabilities cannot express this problem class, if they cannot."""
    if problem_class in QUADRATIC_CLASSES and not caps.supports_quadratic:
        return REASON_QUADRATIC_TERMS
    integer_classes = {
        ProblemClass.MILP,
        ProblemClass.IP,
        ProblemClass.BIP,
        ProblemClass.MIQP,
        ProblemClass.MIQCP,
    }
    if problem_class in integer_classes:
        # BIP is all-binary, so supports_binary is the flag that matters there;
        # every other integer class can carry general integers.
        needed_flag = (
            caps.supports_binary if problem_class is ProblemClass.BIP else caps.supports_integer
        )
        if not needed_flag:
            return REASON_INTEGER_VARIABLES
    return None


def plan_comparison(
    problem: OptimizationProblem,
    solver_names: list[str],
) -> list[SolverPlanEntry]:
    """Decide, per solver, whether it runs this problem and why not if it does not.

    ``solver_names`` must already be normalized. The problem is classified once
    for the whole plan — classification parses every constraint, so doing it per
    solver would multiply that cost by the number of columns for an answer that
    cannot change between them.
    """
    problem_class = classify(problem)
    plan: list[SolverPlanEntry] = []
    for name in solver_names:
        plan.append(SolverPlanEntry(name, _solver_reason(name, problem_class)))
    return plan


#: How close two objective values must be to count as the same answer. Relative,
#: scaled by the larger magnitude, because an absolute epsilon is meaningless on a
#: problem whose objective runs into the millions.
OBJECTIVE_MATCH_TOLERANCE = 1e-6

#: How close two variable values must be to count as the same assignment.
SOLUTION_MATCH_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SolvedColumn:
    """One finished column, reduced to what agreement is decided on."""

    solver_name: str
    objective_value: float | None
    solution: dict[str, float] | None


@dataclass(frozen=True)
class Agreement:
    """Whether the finished columns tell the same story."""

    compared_solvers: list[str]
    objectives_agree: bool | None
    solutions_identical: bool | None
    max_objective_delta: float | None
    alternative_optima: bool


def compute_agreement(columns: list[SolvedColumn]) -> Agreement:
    """Compare the finished columns against each other.

    Fewer than two columns cannot agree or disagree, so the booleans stay None
    rather than defaulting to True. A comparison with one usable result should
    not claim its solvers concur.

    ``alternative_optima`` is the case worth naming: the objectives match but the
    variable assignments do not. Both solvers are right and the problem simply
    has more than one optimal solution. Without this flag a reader sees two
    different solutions and concludes one solver is wrong.
    """
    names = [c.solver_name for c in columns]
    if len(columns) < 2:
        return Agreement(names, None, None, None, False)

    objectives = [c.objective_value for c in columns if c.objective_value is not None]
    objectives_agree: bool | None = None
    max_delta: float | None = None
    if len(objectives) >= 2:
        max_delta = max(objectives) - min(objectives)
        scale = max(1.0, max(abs(v) for v in objectives))
        objectives_agree = max_delta <= OBJECTIVE_MATCH_TOLERANCE * scale

    solutions = [c.solution for c in columns if c.solution is not None]
    solutions_identical: bool | None = None
    if len(solutions) >= 2:
        solutions_identical = _solutions_match(solutions)

    alternative_optima = bool(objectives_agree) and solutions_identical is False
    return Agreement(names, objectives_agree, solutions_identical, max_delta, alternative_optima)


def _solutions_match(solutions: list[dict[str, float]]) -> bool:
    """Every solution assigns the same value to the same variables."""
    reference = solutions[0]
    reference_keys = set(reference)
    for other in solutions[1:]:
        if set(other) != reference_keys:
            return False
        for name, value in reference.items():
            if abs(other[name] - value) > SOLUTION_MATCH_TOLERANCE:
                return False
    return True


def _solver_reason(name: str, problem_class: ProblemClass) -> str | None:
    """Reason ``name`` cannot take part, or None when it can."""
    excluded = PERMANENTLY_EXCLUDED.get(name)
    if excluded is not None:
        return excluded
    try:
        adapter = registry.get(name)
    except SolverNotFoundError:
        return REASON_NOT_REGISTERED
    except SolverUnavailableError:
        return REASON_NOT_AVAILABLE
    return _capability_reason(adapter.capabilities, problem_class)


__all__ = [
    "OBJECTIVE_MATCH_TOLERANCE",
    "PERMANENTLY_EXCLUDED",
    "REASON_INTEGER_VARIABLES",
    "REASON_NOT_AVAILABLE",
    "REASON_NOT_REGISTERED",
    "REASON_QUADRATIC_TERMS",
    "SOLUTION_MATCH_TOLERANCE",
    "UNSUPPORTED_SOLVER_STATUS",
    "Agreement",
    "SolvedColumn",
    "SolverPlanEntry",
    "build_comparison_problem",
    "compute_agreement",
    "normalize_solver_names",
    "plan_comparison",
]
