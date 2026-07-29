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


def validate_problem(problem: OptimizationProblem) -> None:
    """Validate an optimization problem. Raises ``InvalidProblemError`` if invalid."""
    variable_names = {v.name for v in problem.variables}

    obj_vars = extract_variable_names(problem.objective.expression)
    invalid_obj_vars = obj_vars - variable_names
    if invalid_obj_vars:
        raise InvalidProblemError(f"Objective references undefined variables: {invalid_obj_vars}")

    for i, constraint in enumerate(problem.constraints):
        constraint_vars = extract_variable_names(constraint.expression)
        invalid_vars = constraint_vars - variable_names
        if invalid_vars:
            raise InvalidProblemError(
                f"Constraint {constraint.name or i} references undefined variables: {invalid_vars}"
            )

    for var in problem.variables:
        if var.lower_bound is not None and var.upper_bound is not None:
            if var.lower_bound > var.upper_bound:
                raise InvalidProblemError(
                    f"Variable {var.name} has invalid bounds: {var.lower_bound} > {var.upper_bound}"
                )

        if var.type.value == "binary":
            if var.lower_bound is not None and var.lower_bound < 0:
                raise InvalidProblemError(f"Binary variable {var.name} cannot have lower bound < 0")
            if var.upper_bound is not None and var.upper_bound > 1:
                raise InvalidProblemError(f"Binary variable {var.name} cannot have upper bound > 1")
