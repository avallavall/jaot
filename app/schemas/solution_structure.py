"""Best-effort recovery of variable index structure from flat names.

JModel-compiled problems carry authoritative ``family`` / ``index_tuple`` on
each :class:`Variable` (the compiler knows the real index sets). Flat and
imported problems (MPS / LP / CIP / JSON, or a hand-authored problem) carry
none — here we parse the conventional ``<family>_<i>_<j>`` naming. An index
segment must LOOK like an index label: purely numeric (``3``) or a letter
prefix ending in digits (``s1``, ``o107`` — the MDPDP-style composite naming).
A purely alphabetic trailing segment is never an index (``total_cost`` must
not become family ``total``), and the boundary is the maximal index suffix at
segment granularity, so ``xsc_s1_c1_k1`` reads as family ``xsc`` over
``(s1, c1, k1)`` while ``x_cost_3`` keeps its underscored family ``x_cost``.
Anything that doesn't parse cleanly is left unstructured and renders flat —
the graceful fallback the analysis layer relies on.
"""

import re

from app.schemas.optimization import OptimizationProblem

# family = one or more letter-led identifier segments ("x", "assign", "x_cost");
# indices = one or more underscore-separated index-shaped segments — numeric
# ("3") or letters-then-digits ("s1", "o107"). The family's extra segments are
# LAZY, so the index suffix is maximal: the digit-bearing tail of
# "xsc_s1_c1_k1" belongs to the indices, not the family. Purely alphabetic
# segments never match the index shape — see the module docstring.
_IDX_SEGMENT = r"[A-Za-z]*\d+"
_FLAT_NAME = re.compile(
    rf"^(?P<family>[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z][A-Za-z0-9]*)*?)"
    rf"_(?P<idx>{_IDX_SEGMENT}(?:_{_IDX_SEGMENT})*)$"
)


def parse_flat_name(name: str) -> tuple[str, list[str]] | None:
    """Split ``"assign_3_5"`` / ``"xsc_s1_c1_k1"`` into family + indices, or ``None``.

    Returns ``None`` for names whose index structure can't be recovered
    unambiguously (a trailing segment that is neither numeric nor
    letters-then-digits, or no index suffix at all).
    """
    match = _FLAT_NAME.match(name)
    if match is None:
        return None
    return match.group("family"), match.group("idx").split("_")


def annotate_variable_structure(problem: OptimizationProblem) -> None:
    """Fill ``family`` / ``index_tuple`` on a problem's variables, in place.

    No-op when ANY variable already carries a family: that means the JModel
    compiler annotated this problem authoritatively, and we must neither
    second-guess it nor parse the genuine scalars it deliberately left
    unstructured. Only truly flat/imported problems get the heuristic parse.
    """
    variables = problem.variables
    if any(v.family for v in variables):
        return
    for var in variables:
        parsed = parse_flat_name(var.name)
        if parsed is not None:
            var.family, var.index_tuple = parsed
