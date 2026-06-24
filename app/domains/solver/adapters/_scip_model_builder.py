"""Shared SCIP model builder — absorbed into adapters/ per Phase 4 Plan 03 / D-07.

Constructs a PySCIPOpt Model from an OptimizationProblem.  Used by both
SCIPAdapter (for solving) and FileExportService (for writeProblem).

Original path: app/domains/solver/services/model_builder.py
Canonical path: app/domains/solver/adapters/_scip_model_builder.py
"""

from __future__ import annotations

import logging
from typing import Any

from pyscipopt import Model

from app.domains.solver.adapters._scip_expression import build_scip_expression
from app.domains.solver.services.expression_parser import ExpressionParser
from app.schemas.optimization import (
    Constraint,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)

logger = logging.getLogger(__name__)

# SCIP variable type codes
_VTYPE_MAP = {
    VariableType.BINARY: "B",
    VariableType.INTEGER: "I",
    VariableType.CONTINUOUS: "C",
}


def build_scip_model(
    problem: OptimizationProblem,
    parser: ExpressionParser | None = None,
) -> tuple[Model, dict[str, Any], dict[str, Any]]:
    """Build a SCIP Model from an OptimizationProblem.

    Args:
        problem: The optimization problem definition.
        parser: ExpressionParser instance (created if not provided).

    Returns:
        Tuple of (model, scip_vars dict, constraint_refs dict).
    """
    if parser is None:
        parser = ExpressionParser()

    model = Model(problem.name or "optimization_problem")
    model.hideOutput()

    scip_vars = create_variables(model, problem.variables)
    variable_names = [v.name for v in problem.variables]
    constraint_refs = add_constraints(model, scip_vars, problem.constraints, variable_names, parser)
    set_objective(model, scip_vars, problem.objective, variable_names, parser)

    return model, scip_vars, constraint_refs


def create_variables(model: Model, variables: list[Variable]) -> dict[str, Any]:
    """Create SCIP variables from problem variable definitions."""
    scip_vars: dict[str, Any] = {}

    for var in variables:
        lb = var.lower_bound if var.lower_bound is not None else None
        ub = var.upper_bound if var.upper_bound is not None else None

        if var.type == VariableType.BINARY:
            scip_var = model.addVar(name=var.name, vtype="B")
        elif var.type == VariableType.INTEGER:
            scip_var = model.addVar(name=var.name, vtype="I", lb=lb, ub=ub)
        else:
            scip_var = model.addVar(name=var.name, vtype="C", lb=lb, ub=ub)

        scip_vars[var.name] = scip_var

    return scip_vars


def add_constraints(
    model: Model,
    scip_vars: dict[str, Any],
    constraints: list[Constraint],
    variable_names: list[str],
    parser: ExpressionParser,
) -> dict[str, Any]:
    """Parse and add constraints to a SCIP model."""
    constraint_refs: dict[str, Any] = {}

    for i, constraint in enumerate(constraints):
        parsed = parser.parse_constraint(
            constraint.expression,
            known_variables=variable_names,
        )
        lhs_expr = build_scip_expression(parsed.lhs, scip_vars)
        name = constraint.name or f"c{i}"

        if parsed.operator == "<=":
            cons = model.addCons(lhs_expr <= parsed.rhs, name=name)
        elif parsed.operator == ">=":
            cons = model.addCons(lhs_expr >= parsed.rhs, name=name)
        elif parsed.operator in ("==", "="):
            cons = model.addCons(lhs_expr == parsed.rhs, name=name)
        elif parsed.operator == "<":
            cons = model.addCons(lhs_expr <= parsed.rhs - 1e-6, name=name)
        elif parsed.operator == ">":
            cons = model.addCons(lhs_expr >= parsed.rhs + 1e-6, name=name)
        else:
            cons = None

        if cons is not None:
            constraint_refs[name] = cons

    return constraint_refs


def set_objective(
    model: Model,
    scip_vars: dict[str, Any],
    objective: Any,
    variable_names: list[str],
    parser: ExpressionParser,
) -> None:
    """Parse and set the objective function on a SCIP model."""
    parsed = parser.parse_expression(
        objective.expression,
        known_variables=variable_names,
    )
    obj_expr = build_scip_expression(parsed, scip_vars)
    sense = "minimize" if objective.sense == ObjectiveSense.MINIMIZE else "maximize"
    model.setObjective(obj_expr, sense=sense)
