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

from typing import Any

from pyscipopt import Variable as SCIPVariable  # noqa: F401  (used in type hint)

from app.domains.solver.services.expression_parser import ParsedExpression


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
