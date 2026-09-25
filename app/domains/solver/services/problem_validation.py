"""Structural validation of an OptimizationProblem, before any solver sees it.

Undefined variables in the objective or a constraint, bounds that cross, a
binary declared outside [0, 1] — the checks that make a problem ill-formed
whoever is asked to solve it. Nothing here is solver-specific, and nothing here
knows about HTTP: it raises :class:`InvalidProblemError`, and whichever layer is
serving the request decides what that looks like on the wire (today: 400, with
this exact message).

It lived in ``app/services/solve_orchestrator.py``, which meant the solver
domain had to reach up into the platform to validate its own input (D-16).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domains.solver.services.expression_parser import ExpressionParser
from app.schemas.optimization import OptimizationProblem

# Function names an expression may contain that are not variable references.
_EXCLUDED_TOKENS = {
    "sin",
    "cos",
    "tan",
    "exp",
    "log",
    "sqrt",
    "abs",
    "min",
    "max",
    "sum",
}


class InvalidProblemError(ValueError):
    """A problem that no solver could be asked to solve.

    Carries the human-readable reason as ``detail`` so the serving layer can
    pass it through unchanged, and the issue's ``code`` and ``params`` so a
    localized page can say it in the reader's language.
    """

    def __init__(
        self,
        detail: str,
        code: str | None = None,
        params: dict[str, str | int | float] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.params = params or {}


@dataclass(frozen=True)
class ProblemIssue:
    """One thing wrong with a problem, in English and as a code a page can translate.

    The English ``message`` is the API contract and is unchanged. It is not a
    sentence to show a user: "references undefined variables: {'q'}" prints a
    Python set, and "EXPR_PARSE_ERROR: Unexpected token" is the parser's own
    diagnostic. A page renders ``code`` with ``params`` instead.
    """

    message: str
    code: str
    params: dict[str, str | int | float] = field(default_factory=dict)


def _names(names: set[str]) -> str:
    """Variable names for a sentence: sorted, comma separated."""
    return ", ".join(sorted(names))


# A number literal that does not sit inside a name, with the exponent the
# tokenizer also accepts. Without removing these first, "5e-05*x" reported an
# undefined variable "e", and every imported file with a coefficient below 1e-4
# was refused with a 400.
_NUMBER_LITERAL = re.compile(r"(?<![A-Za-z0-9_])(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def extract_variable_names(expression: str) -> set[str]:
    """Extract variable names from a mathematical expression."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", _NUMBER_LITERAL.sub(" ", expression))
    return {t for t in tokens if t not in _EXCLUDED_TOKENS}


def iter_problem_errors(problem: OptimizationProblem) -> list[str]:
    """Every structural problem found, not just the first one.

    A caller who asked "is this valid?" wants the list. Reporting one error at a
    time turns fixing a hand-written model into as many round trips as it has
    mistakes — and hides, for instance, that the constraints are broken too while
    the author is still staring at the objective.
    """
    return [issue.message for issue in iter_problem_issues(problem)]


def iter_problem_issues(problem: OptimizationProblem) -> list[ProblemIssue]:
    """Every structural problem found, each with the code a page translates."""
    issues: list[ProblemIssue] = []
    variable_names = {v.name for v in problem.variables}
    # The same parser every solver adapter runs at solve time. Name checks alone
    # let "x <= <= 3" through as valid — the validator said yes and the solve
    # then failed on the very expression it had approved, which is backwards:
    # the typical caller is an agent validating precisely to avoid buying a
    # doomed solve (measured against production, 2026-08-02).
    parser = ExpressionParser()

    obj_vars = extract_variable_names(problem.objective.expression)
    invalid_obj_vars = obj_vars - variable_names
    if invalid_obj_vars:
        issues.append(
            ProblemIssue(
                message=f"Objective references undefined variables: {invalid_obj_vars}",
                code="problem.objective_undefined_variables",
                params={"names": _names(invalid_obj_vars)},
            )
        )
    try:
        parser.parse_expression(problem.objective.expression)
    except ValueError as e:  # ParseError, or float() on a malformed number
        issues.append(
            ProblemIssue(
                message=f"Objective expression cannot be parsed: {e}",
                code="problem.objective_unreadable",
            )
        )

    for i, constraint in enumerate(problem.constraints):
        label = constraint.name or str(i)
        constraint_vars = extract_variable_names(constraint.expression)
        invalid_vars = constraint_vars - variable_names
        if invalid_vars:
            issues.append(
                ProblemIssue(
                    message=f"Constraint {label} references undefined variables: {invalid_vars}",
                    code="problem.constraint_undefined_variables",
                    params={"constraint": label, "names": _names(invalid_vars)},
                )
            )
        try:
            parser.parse_constraint(constraint.expression)
        except ValueError as e:  # ParseError, or float() on a malformed number
            issues.append(
                ProblemIssue(
                    message=f"Constraint {label} cannot be parsed: {e}",
                    code="problem.constraint_unreadable",
                    params={"constraint": label},
                )
            )

    for var in problem.variables:
        if var.lower_bound is not None and var.upper_bound is not None:
            if var.lower_bound > var.upper_bound:
                issues.append(
                    ProblemIssue(
                        message=(
                            f"Variable {var.name} has invalid bounds: "
                            f"{var.lower_bound} > {var.upper_bound}"
                        ),
                        code="problem.bounds_cross",
                        params={
                            "variable": var.name,
                            "lower": var.lower_bound,
                            "upper": var.upper_bound,
                        },
                    )
                )

        if var.type.value == "binary":
            if var.lower_bound is not None and var.lower_bound < 0:
                issues.append(
                    ProblemIssue(
                        message=f"Binary variable {var.name} cannot have lower bound < 0",
                        code="problem.binary_bounds",
                        params={"variable": var.name},
                    )
                )
            if var.upper_bound is not None and var.upper_bound > 1:
                issues.append(
                    ProblemIssue(
                        message=f"Binary variable {var.name} cannot have upper bound > 1",
                        code="problem.binary_bounds",
                        params={"variable": var.name},
                    )
                )

    return issues


def iter_objective_issues(expressions: list[str], variable_names: set[str]) -> list[ProblemIssue]:
    """What is wrong with the objectives of a multi-objective request.

    They are not part of the problem, so :func:`iter_problem_issues` never
    looked at them. An objective naming an undeclared variable reached every
    subproblem, each one failed, and the run came back as an empty front.
    """
    issues: list[ProblemIssue] = []
    parser = ExpressionParser()
    for n, expression in enumerate(expressions, start=1):
        unknown = extract_variable_names(expression) - variable_names
        if unknown:
            issues.append(
                ProblemIssue(
                    message=f"Objective {n} references undefined variables: {unknown}",
                    code="problem.mo_objective_undefined_variables",
                    params={"n": n, "names": _names(unknown)},
                )
            )
        try:
            parser.parse_expression(expression)
        except ValueError as e:  # ParseError, or float() on a malformed number
            issues.append(
                ProblemIssue(
                    message=f"Objective {n} expression cannot be parsed: {e}",
                    code="problem.mo_objective_unreadable",
                    params={"n": n},
                )
            )
    return issues


def validate_problem(problem: OptimizationProblem) -> None:
    """Validate an optimization problem. Raises ``InvalidProblemError`` if invalid.

    Raises on the first error: a solve is refused either way, and this message is
    a 400 body. Use :func:`iter_problem_errors` when the caller wants the list.
    """
    raise_first(iter_problem_issues(problem))


def raise_first(issues: list[ProblemIssue]) -> None:
    """Raise ``InvalidProblemError`` for the first issue, if there is one."""
    if issues:
        first = issues[0]
        raise InvalidProblemError(first.message, code=first.code, params=first.params)
