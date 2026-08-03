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
    pass it through unchanged.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def extract_variable_names(expression: str) -> set[str]:
    """Extract variable names from a mathematical expression."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expression)
    return {t for t in tokens if t not in _EXCLUDED_TOKENS}


def iter_problem_errors(problem: OptimizationProblem) -> list[str]:
    """Every structural problem found, not just the first one.

    A caller who asked "is this valid?" wants the list. Reporting one error at a
    time turns fixing a hand-written model into as many round trips as it has
    mistakes — and hides, for instance, that the constraints are broken too while
    the author is still staring at the objective.
    """
    errors: list[str] = []
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
        errors.append(f"Objective references undefined variables: {invalid_obj_vars}")
    try:
        parser.parse_expression(problem.objective.expression)
    except ValueError as e:  # ParseError, or float() on a malformed number
        errors.append(f"Objective expression cannot be parsed: {e}")

    for i, constraint in enumerate(problem.constraints):
        constraint_vars = extract_variable_names(constraint.expression)
        invalid_vars = constraint_vars - variable_names
        if invalid_vars:
            errors.append(
                f"Constraint {constraint.name or i} references undefined variables: {invalid_vars}"
            )
        try:
            parser.parse_constraint(constraint.expression)
        except ValueError as e:  # ParseError, or float() on a malformed number
            errors.append(f"Constraint {constraint.name or i} cannot be parsed: {e}")

    for var in problem.variables:
        if var.lower_bound is not None and var.upper_bound is not None:
            if var.lower_bound > var.upper_bound:
                errors.append(
                    f"Variable {var.name} has invalid bounds: {var.lower_bound} > {var.upper_bound}"
                )

        if var.type.value == "binary":
            if var.lower_bound is not None and var.lower_bound < 0:
                errors.append(f"Binary variable {var.name} cannot have lower bound < 0")
            if var.upper_bound is not None and var.upper_bound > 1:
                errors.append(f"Binary variable {var.name} cannot have upper bound > 1")

    return errors


def validate_problem(problem: OptimizationProblem) -> None:
    """Validate an optimization problem. Raises ``InvalidProblemError`` if invalid.

    Raises on the first error: a solve is refused either way, and this message is
    a 400 body. Use :func:`iter_problem_errors` when the caller wants the list.
    """
    errors = iter_problem_errors(problem)
    if errors:
        raise InvalidProblemError(errors[0])
