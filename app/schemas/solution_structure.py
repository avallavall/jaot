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

    Names the strict form cannot read get a second, wider attempt that also
    accepts an index written as ``<tag>_<ordinal>`` — see
    :func:`_parse_underscored_indices`.
    """
    match = _FLAT_NAME.match(name)
    if match is not None:
        return match.group("family"), match.group("idx").split("_")
    return _parse_underscored_indices(name)


def _is_index_token(token: str) -> bool:
    """``"3"`` / ``"s1"`` — an index label written as a single segment.

    Deliberately reuses the strict pattern's own definition so the two readings
    can never drift into disagreeing about what an index looks like.
    """
    return re.fullmatch(_IDX_SEGMENT, token) is not None


def _parse_underscored_indices(name: str) -> tuple[str, list[str]] | None:
    """Read names whose index labels themselves contain an underscore.

    Routing generators name nodes ``o_0`` / ``p_1`` / ``d_2``, so an arc becomes
    ``x_o_0_p_1_2`` — six segments for what is really ``x[o_0, p_1, 2]``. The
    strict pattern rejects it outright (``o`` is purely alphabetic, so it can
    never be an index), which left every arc variable of such a model
    unstructured: no family, no grouping, no map.

    Accepting ``<tag>_<ordinal>`` as ONE index is inherently ambiguous — it is
    the same shape as the flat name ``x_cost_3``, which must keep family
    ``x_cost``. The ambiguity is resolved by ORDER, not by cleverness: this
    function only ever runs on names the strict parse already refused, so it can
    add structure where there was none and can never reinterpret a name that
    already reads correctly.

    The family is the SHORTEST leading run of segments that lets the remainder
    parse as indices, keeping the index suffix maximal exactly as the strict
    pattern does.

    Known limit: a name that parses strictly but *wrongly* is not repaired here,
    because nothing in the name distinguishes it from a legitimate reading. In
    the same routing model ``s_p_0_1`` (arrival time at node ``p_0`` for vehicle
    ``1``) parses as family ``s_p`` over ``(0, 1)``, and telling that apart from
    ``x_cost_3`` would take a guess this module deliberately refuses to make.
    """
    tokens = name.split("_")
    if len(tokens) < 3:
        # Nothing to gain: 2 tokens can only be family+index, which the strict
        # pattern already covers.
        return None
    if not tokens[0] or not tokens[0][0].isalpha():
        return None

    # Try the shortest family first so the index suffix stays maximal.
    for split_at in range(1, len(tokens) - 1):
        family_tokens = tokens[:split_at]
        if not all(t and t[0].isalpha() and t.isalnum() for t in family_tokens):
            break  # a non-identifier segment cannot be part of a family
        indices = _read_indices(tokens[split_at:])
        if indices:
            return "_".join(family_tokens), indices
    return None


def _read_indices(tokens: list[str]) -> list[str] | None:
    """Consume ``tokens`` as a sequence of index labels, or ``None``.

    A label is a single index-shaped token (``3``, ``s1``) or an alphabetic tag
    paired with the ordinal that follows it (``o`` + ``0`` -> ``o_0``).
    """
    labels: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if _is_index_token(token):
            labels.append(token)
            i += 1
            continue
        # A tag only counts when an ordinal actually follows it; a trailing
        # alphabetic segment is never an index (that is what keeps "total_cost"
        # flat).
        if token.isalpha() and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            labels.append(f"{token}_{tokens[i + 1]}")
            i += 2
            continue
        return None
    return labels or None


def index_components(index_tuple: list[str]) -> list[str]:
    """Flatten an ``index_tuple`` into its individual index labels.

    ``index_tuple`` has one entry per index SET, so a variable over a single
    3-dimensional tuple set arrives as ``["s2_c2_k2"]`` — one entry holding three
    components joined with "_" (see the compiler's ``_mangle`` site). A name
    recovered from a flat model instead arrives already split, but its labels may
    themselves contain an underscore: ``["o_0", "p_0", "0"]``.

    Both must read as three components, and telling them apart is exactly the
    job :func:`_read_indices` already does — reusing it keeps ONE definition of
    what an index label looks like instead of a second copy that would drift.

    Entries that cannot be read are passed through whole rather than guessed at.
    """
    components: list[str] = []
    for entry in index_tuple:
        if "_" not in entry:
            components.append(entry)
            continue
        parsed = _read_indices(entry.split("_"))
        components.extend(parsed if parsed else [entry])
    return components


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
