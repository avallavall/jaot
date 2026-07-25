"""Recover the graph a solved model describes, when it describes one.

Thousands of chips reading ``xsc_s2_c2_k2 = 1`` are a routing plan nobody can
see. Any variable family indexed by two or more labels IS an edge list — arcs in
a pickup-and-delivery model, worker-to-task in an assignment, item-to-bin in
packing — so the active entries of such a family can be drawn as a graph instead
of read as text.

**What this does NOT do.** It does not place nodes in space. Optimization models
carry distances, not coordinates (``dist_sc`` is a cost, not a position), so any
"map" with geography in it would be invented. Nodes are assigned to LAYERS by
their position in the flow, which is a fact the edges actually contain.

The whole thing declines cleanly: a model with no multi-index family, or one
whose solution activates nothing, returns ``None`` and the caller shows nothing
rather than an empty box.
"""

from __future__ import annotations

from collections import defaultdict

from app.schemas.optimization import (
    GraphEdge,
    OptimizationProblem,
    SolutionGraph,
    VariableType,
)
from app.schemas.solution_structure import index_components

#: A binary at 1 in a MIP can come back as 0.9999999997.
_ACTIVE_EPS = 0.5
#: Continuous flows have no natural threshold; anything above noise is an edge.
_NONZERO_EPS = 1e-9
#: Past this the picture is a hairball that tells the reader less than the table
#: it replaced, so we stop drawing and say how much was left out.
MAX_EDGES = 400


def build_solution_graph(
    problem: OptimizationProblem,
    solution: dict[str, float] | None,
) -> SolutionGraph | None:
    """Build the graph of the active edges, or ``None`` if there is none to draw.

    Reads the authoritative ``family`` / ``index_tuple`` the JModel compiler
    stamps, falling back to whatever the flat-name parser recovered. Both arrive
    in different shapes, which :func:`index_components` reconciles.
    """
    if not solution:
        return None

    # Group candidate edge variables by family, keeping only families whose
    # every member exposes at least two index components. A family with mixed
    # arity is not an edge list — it is a parse we should not trust.
    by_family: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for var in problem.variables:
        if not var.family or not var.index_tuple:
            continue
        components = index_components(var.index_tuple)
        if len(components) < 2:
            continue
        by_family[var.family].append((var.name, components))

    if not by_family:
        return None

    types = {v.name: v.type for v in problem.variables}
    graph = SolutionGraph()
    seen_groups: dict[str, None] = {}
    edges: list[GraphEdge] = []

    for family in sorted(by_family):
        members = by_family[family]
        arity = {len(c) for _, c in members}
        if len(arity) != 1:
            # Inconsistent arity within one family — decline rather than draw a
            # graph whose edges mean different things.
            continue
        graph.candidate_count += len(members)
        family_used = False
        for name, components in members:
            value = solution.get(name)
            if value is None:
                continue
            is_discrete = types.get(name) in (VariableType.BINARY, VariableType.INTEGER)
            threshold = _ACTIVE_EPS if is_discrete else _NONZERO_EPS
            if abs(value) < threshold:
                continue
            group = "_".join(components[2:]) if len(components) > 2 else None
            edges.append(
                GraphEdge(
                    variable=name,
                    source=components[0],
                    target=components[1],
                    group=group,
                    value=value,
                    family=family,
                )
            )
            if group is not None:
                seen_groups.setdefault(group, None)
            family_used = True
        if family_used:
            graph.families.append(family)

    if not edges:
        return None

    graph.active_count = len(edges)
    if len(edges) > MAX_EDGES:
        graph.truncated = True
        edges = edges[:MAX_EDGES]
    graph.edges = edges
    graph.groups = list(seen_groups)

    sources = {e.source for e in edges}
    targets = {e.target for e in edges}
    graph.is_network = bool(sources & targets)

    nodes = sorted(sources | targets)
    graph.nodes = nodes
    graph.layers = _assign_layers(nodes, edges)
    return graph


def _assign_layers(nodes: list[str], edges: list[GraphEdge]) -> dict[str, int]:
    """Longest-path layering: a node sits one level after its deepest predecessor.

    This is the layout decision, and it is derived purely from the edges — no
    geometry is invented. A model with cycles (a tour that returns to its depot)
    has no such ordering, so the relaxation is explicit: nodes still on the
    worklist when no progress is possible keep the depth they reached, which
    degrades to a readable left-to-right flow instead of failing.
    """
    incoming: dict[str, list[str]] = {n: [] for n in nodes}
    for edge in edges:
        incoming[edge.target].append(edge.source)

    depth = {n: 0 for n in nodes}
    # Bounded relaxation: |V| passes settle any acyclic graph, and cap the work
    # on a cyclic one instead of spinning.
    for _ in range(len(nodes)):
        changed = False
        for node in nodes:
            for pred in incoming[node]:
                if pred == node:
                    continue  # a self-loop cannot deepen anything
                if depth[pred] + 1 > depth[node]:
                    depth[node] = depth[pred] + 1
                    changed = True
        if not changed:
            break
    return depth
