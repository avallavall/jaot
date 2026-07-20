"""Best-effort recovery of variable index structure from flat names.

JModel-compiled problems carry authoritative ``family`` / ``index_tuple`` on
each :class:`Variable` (the compiler knows the real index sets). Flat and
imported problems (MPS / LP / CIP / JSON, or a hand-authored problem) carry
none — here we parse the conventional ``<family>_<i>_<j>`` naming, but only
when the trailing index segments are PURELY NUMERIC. A family name or an index
label can itself contain underscores, so the family/index boundary is genuinely
irrecoverable from the string in the general case; guessing there would mislabel
variables. Anything that doesn't parse cleanly is left unstructured and renders
flat — the graceful fallback the analysis layer relies on.
"""

import re

from app.schemas.optimization import OptimizationProblem

# family = one or more letter-led identifier segments ("x", "assign", "x_cost");
# indices = one or more underscore-separated purely-numeric segments ("3", "3_5").
# Deliberately conservative — see the module docstring for why numeric-only.
_FLAT_NAME = re.compile(
    r"^(?P<family>[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z][A-Za-z0-9]*)*)_(?P<idx>\d+(?:_\d+)*)$"
)


def parse_flat_name(name: str) -> tuple[str, list[str]] | None:
    """Split ``"assign_3_5"`` into ``("assign", ["3", "5"])``, or ``None``.

    Returns ``None`` for names whose index structure can't be recovered
    unambiguously (non-numeric index labels, no index suffix at all).
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
