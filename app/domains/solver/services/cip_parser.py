"""CIP file parser for extracting constraints from SCIP's CIP format.

When SCIP's getValsLinear() fails (non-linear constraints, etc.), we fall back
to writing the model as CIP and parsing the text representation. This module
handles that parsing.

CIP constraint format (linear section):
  [linear] constraint_name: +1.5<x1> -2<x2> +3<y> <= 10;
"""

import logging
import re

from app.domains.solver.services._naming import sanitize_var_name
from app.schemas.optimization import Constraint

logger = logging.getLogger(__name__)

# Matches a [linear] constraint line in CIP format.
# Groups: name, body (terms + operator + rhs)
_LINEAR_RE = re.compile(
    r"\[linear\]\s+([^:]+):\s+(.+);",
    re.IGNORECASE,
)

# Matches individual coefficient-variable terms like +1.5<x1> or -2<y>
_TERM_RE = re.compile(r"([+-]?\s*[\d.]*)\s*<([^>]+)>")

# Matches the comparison operator and RHS at the end of the body
_OP_RHS_RE = re.compile(r"(<=|>=|==)\s*([+-]?\s*[\d.eE+\-]+)\s*$")


_sanitize_var_name = sanitize_var_name  # local alias for brevity


def parse_cip_constraints(cip_path: str) -> list[Constraint]:
    """Parse constraints from a CIP file written by SCIP.

    Args:
        cip_path: Path to the .cip file on disk.

    Returns:
        List of Constraint objects extracted from [linear] sections.
    """
    with open(cip_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    constraints: list[Constraint] = []

    for match in _LINEAR_RE.finditer(content):
        raw_name = match.group(1).strip()
        body = match.group(2).strip()

        parsed = _parse_constraint_body(body)
        if parsed is None:
            logger.debug("Skipping unparseable CIP constraint: %s", raw_name)
            continue

        expression, op, rhs = parsed
        constraint_expr = f"{expression} {op} {rhs}"

        name = _sanitize_var_name(raw_name) if raw_name else None
        constraints.append(Constraint(name=name, expression=constraint_expr))

    logger.info("Parsed %d constraints from CIP file", len(constraints))
    return constraints


def _parse_constraint_body(
    body: str,
) -> tuple[str, str, str] | None:
    """Parse the body of a CIP constraint line.

    Args:
        body: The part after the colon, e.g. "+1.5<x1> -2<x2> <= 10"

    Returns:
        Tuple of (lhs_expression, operator, rhs_value) or None if unparseable.
    """
    op_match = _OP_RHS_RE.search(body)
    if not op_match:
        return None

    operator = op_match.group(1)
    rhs = op_match.group(2).strip()
    lhs_part = body[: op_match.start()].strip()

    terms = _TERM_RE.findall(lhs_part)
    if not terms:
        return None

    expression_parts: list[str] = []
    for coeff_str, var_name in terms:
        coeff_str = coeff_str.replace(" ", "").strip()
        sanitized_name = _sanitize_var_name(var_name)

        if not coeff_str or coeff_str == "+":
            coeff_str = "1"
        elif coeff_str == "-":
            coeff_str = "-1"

        try:
            coeff = float(coeff_str)
        except ValueError:
            continue

        if coeff == 1.0:
            expression_parts.append(f"+{sanitized_name}")
        elif coeff == -1.0:
            expression_parts.append(f"-{sanitized_name}")
        elif coeff >= 0:
            expression_parts.append(f"+{coeff}*{sanitized_name}")
        else:
            expression_parts.append(f"{coeff}*{sanitized_name}")

    if not expression_parts:
        return None

    expression = " ".join(expression_parts).strip()
    if expression.startswith("+"):
        expression = expression[1:].strip()

    return expression, operator, rhs
