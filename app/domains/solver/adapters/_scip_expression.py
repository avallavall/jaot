"""Private SCIP expression builder — D-06.

This module is the adapter's exclusive owner of the "turn a ParsedExpression
into a SCIP expression object" logic. It is allowed to import pyscipopt
because it lives under `app/domains/solver/adapters/`, which the
import-linter contract `solver-services-no-pyscipopt` does NOT restrict.

Why underscore-prefixed module name: this file is an implementation detail
of SCIPAdapter. External code must not import it — use
`SCIPAdapter._build_expression()` instead.

Phase 4 / Plan 02 / SOLV-06 / D-05 / D-06.
"""

from __future__ import annotations

import logging
from typing import Any

from pyscipopt import Variable as SCIPVariable  # noqa: F401  (used in type hint)

from app.domains.solver.services.expression_parser import ParsedExpression

logger = logging.getLogger(__name__)


def build_scip_expression(
    parsed: ParsedExpression,
    scip_vars: dict[str, SCIPVariable],
) -> Any:
    """Build a SCIP expression from a ParsedExpression.

    Byte-identical port of the former
    `ExpressionParser.build_scip_expression()` method (expression_parser.py
    lines 714-747 pre-Phase-4). Returns whatever object PySCIPOpt constructs
    from `coefficient * scip_var` arithmetic — typed as Any because
    pyscipopt's Expr class is not publicly exported.

    Args:
        parsed: ParsedExpression from ExpressionParser.parse_expression()
        scip_vars: Dict mapping variable names to SCIP Variable instances

    Raises:
        ValueError: Unknown variable name or term with >2 variables.
    """
    expr = parsed.constant

    for term in parsed.terms:
        if not term.variables:
            expr += term.coefficient
        elif len(term.variables) == 1:
            var_name = term.variables[0]
            if var_name not in scip_vars:
                raise ValueError(f"Unknown variable: {var_name}")
            expr += term.coefficient * scip_vars[var_name]
        elif len(term.variables) == 2:
            var1, var2 = term.variables
            if var1 not in scip_vars or var2 not in scip_vars:
                raise ValueError(f"Unknown variable in quadratic term: {var1}*{var2}")
            expr += term.coefficient * scip_vars[var1] * scip_vars[var2]
        else:
            raise ValueError("Terms with more than 2 variables not supported")

    return expr


def anchor_constant_expr(
    expr: Any,
    scip_vars: dict[str, SCIPVariable],
    *,
    label: str = "",
) -> Any:
    """Keep a constraint LHS a SCIP expression even when it has no variable terms.

    A constant LHS (the parser bound no variables — common for parametric/indexed
    expressions the flat parser can't resolve) would make ``expr <op> rhs`` a plain
    Python bool, which pyscipopt's ``addCons`` rejects with "given constraint is not
    ExprCons but bool" and aborts the whole model. Anchoring the constant to a
    zero-weighted variable keeps it a valid SCIP expression that SCIP treats as
    redundant when satisfied and infeasible when violated — never a crash.

    Objectives must NOT use this: ``setObjective`` accepts a bare constant.
    """
    if isinstance(expr, (int, float)) and scip_vars:
        logger.warning(
            "Constraint '%s' has no variable terms (constant LHS %s); anchoring it to a "
            "zero-weighted variable so the model stays buildable.",
            label or "?",
            expr,
        )
        return expr + 0 * next(iter(scip_vars.values()))
    return expr
