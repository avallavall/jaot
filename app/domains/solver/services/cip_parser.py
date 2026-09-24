"""CIP file parser for extracting constraints from SCIP's CIP format.

When SCIP's getValsLinear() fails (non-linear constraints, etc.), we fall back
to writing the model as CIP and parsing the text representation. This module
handles that parsing.

CIP constraint rows, as SCIP writes them:
  [linear] <c1>:  +1e-05<x.1>[C] +<x_1>[C] <= 4;
  [linear] <rng>: -5 <= <x.1>[C] -<x_1>[C] <= 10;
  [linear] <big>:  +2<x>[C] [free];
  [nonlinear] <q1>: <x>*<x>+<y>*<y> <= 8;

Only linear rows are imported. Every other row is reported, never dropped: a
model solved without some of its rows is a different model, and the old parser
solved it anyway and called the answer optimal.
"""

import logging
import re
from collections import Counter

from app.domains.solver.services._naming import sanitize_var_name
from app.schemas.optimization import Constraint

logger = logging.getLogger(__name__)

# One constraint row: its kind, its name (``<c1>`` in SCIP's output, bare in
# older hand-written files) and its body up to the closing semicolon. Variable
# lines (``[binary] <z>: obj=0, ...``) carry no semicolon and do not match.
_ROW_RE = re.compile(
    r"^\s*\[(\w+)\]\s+(<[^>]*>|[^:<]+?)\s*:\s*(.+);\s*$",
    re.MULTILINE,
)

# One coefficient-variable term such as ``+1.5<x1>[C]``, ``-<y>`` or
# ``+1e-05<x>``. The exponent is part of the number: without it ``+1e-05<x>``
# was read as ``-05<x>``, a coefficient of -5.
_TERM_RE = re.compile(
    r"([+-]?\s*(?:(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)?)\s*<([^>]+)>(?:\[[A-Za-z]\])?"
)

_NUMBER = r"[+-]?\s*(?:inf|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"

# The comparison operator and right-hand side at the end of the body.
_OP_RHS_RE = re.compile(rf"(<=|>=|==)\s*({_NUMBER})\s*$")

# A ranged row: ``lhs <= terms <= rhs``.
_RANGED_RE = re.compile(rf"^\s*({_NUMBER})\s*<=\s*(.+?)\s*<=\s*({_NUMBER})\s*$")


_sanitize_var_name = sanitize_var_name  # local alias for brevity


class UnreadCipRowsError(ValueError):
    """Some constraint rows of the CIP file are not linear rows JAOT can read."""

    def __init__(self, kinds: Counter[str]) -> None:
        self.kinds = kinds
        listed = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        super().__init__(f"Constraint rows that cannot be imported: {listed}.")


def parse_cip_constraints(
    cip_path: str,
    var_names: dict[str, str] | None = None,
    *,
    strict: bool = False,
) -> list[Constraint]:
    """Parse constraints from a CIP file written by SCIP.

    Args:
        cip_path: Path to the .cip file on disk.
        var_names: SCIP variable name -> JAOT variable name, as the import
            assigned them. Without it each name is sanitized on its own, and
            two names that sanitize alike (``x.1`` and ``x_1``) merge.
        strict: Raise :class:`UnreadCipRowsError` when any row is not a linear
            row this parser can read, instead of leaving it out.

    Returns:
        List of Constraint objects extracted from [linear] sections.
    """
    with open(cip_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    constraints: list[Constraint] = []
    unread: Counter[str] = Counter()

    for match in _ROW_RE.finditer(_constraints_section(content)):
        kind = match.group(1).lower()
        raw_name = match.group(2).strip().removeprefix("<").removesuffix(">")
        body = match.group(3).strip()

        if kind != "linear":
            unread[kind] += 1
            continue
        if body.endswith("[free]"):
            continue  # a row with no finite side limits nothing

        rows = _parse_rows(body, var_names)
        if rows is None:
            logger.debug("Unparseable CIP constraint: %s", raw_name)
            unread["unparseable linear"] += 1
            continue

        name = _sanitize_var_name(raw_name) if raw_name else None
        for index, (expression, op, rhs) in enumerate(rows):
            row_name = name if index == 0 or name is None else f"{name}_lb"
            constraints.append(Constraint(name=row_name, expression=f"{expression} {op} {rhs}"))

    if unread and strict:
        raise UnreadCipRowsError(unread)
    logger.info("Parsed %d constraints from CIP file", len(constraints))
    return constraints


def _constraints_section(content: str) -> str:
    """The CONSTRAINTS block of a full CIP file, or the whole text of a fragment."""
    start = re.search(r"^CONSTRAINTS\s*$", content, re.MULTILINE)
    if start is None:
        return content
    end = re.search(r"^END\s*$", content[start.end() :], re.MULTILINE)
    return content[start.end() : start.end() + end.start()] if end else content[start.end() :]


def _parse_rows(
    body: str, var_names: dict[str, str] | None = None
) -> list[tuple[str, str, str]] | None:
    """The one or two JAOT rows a linear CIP row stands for, or None."""
    ranged = _RANGED_RE.match(body)
    if ranged:
        lower = ranged.group(1).replace(" ", "")
        upper = ranged.group(3).replace(" ", "")
        expression = _linear_expression(ranged.group(2), var_names)
        if expression is None:
            return None
        return [(expression, "<=", upper), (expression, ">=", lower)]

    parsed = _parse_constraint_body(body, var_names)
    return [parsed] if parsed is not None else None


def _parse_constraint_body(
    body: str,
    var_names: dict[str, str] | None = None,
) -> tuple[str, str, str] | None:
    """Parse the body of a CIP constraint line.

    Args:
        body: The part after the colon, e.g. "+1.5<x1> -2<x2> <= 10"
        var_names: SCIP variable name -> JAOT variable name.

    Returns:
        Tuple of (lhs_expression, operator, rhs_value) or None if unparseable.
    """
    op_match = _OP_RHS_RE.search(body)
    if not op_match:
        return None

    operator = op_match.group(1)
    rhs = op_match.group(2).replace(" ", "")
    expression = _linear_expression(body[: op_match.start()], var_names)
    if expression is None:
        return None
    return expression, operator, rhs


def _linear_expression(lhs_part: str, var_names: dict[str, str] | None) -> str | None:
    terms = _TERM_RE.findall(lhs_part.strip())
    if not terms:
        return None

    expression_parts: list[str] = []
    for coeff_str, var_name in terms:
        coeff_str = coeff_str.replace(" ", "").strip()
        name = (var_names or {}).get(var_name) or _sanitize_var_name(var_name)

        if not coeff_str or coeff_str == "+":
            coeff_str = "1"
        elif coeff_str == "-":
            coeff_str = "-1"

        try:
            coeff = float(coeff_str)
        except ValueError:
            return None

        if coeff == 1.0:
            expression_parts.append(f"+{name}")
        elif coeff == -1.0:
            expression_parts.append(f"-{name}")
        elif coeff >= 0:
            expression_parts.append(f"+{coeff}*{name}")
        else:
            expression_parts.append(f"{coeff}*{name}")

    expression = " ".join(expression_parts).strip()
    if expression.startswith("+"):
        expression = expression[1:].strip()
    return expression
