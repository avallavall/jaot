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
from dataclasses import dataclass

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


@dataclass
class _Family:
    """A variable family with two or more index components, and its domains."""

    name: str
    members: list[tuple[str, list[str]]]
    sources: set[str]
    targets: set[str]
    arity: int
    discrete: bool

    @property
    def is_self_network(self) -> bool:
        """Its two leading dimensions range over the SAME labels.

        That is the signature of an arc family: ``x[i, j]`` where i and j are
        both nodes. It is strong enough evidence on its own, whatever the
        variable type — a continuous ``flow[i, j]`` is every bit an edge.
        """
        return bool(self.sources & self.targets)


def _collect_families(
    problem: OptimizationProblem, types: dict[str, VariableType]
) -> list[_Family]:
    """Group multi-index variables by family, dropping the untrustworthy ones."""
    grouped: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for var in problem.variables:
        if not var.family or not var.index_tuple:
            continue
        components = index_components(var.index_tuple)
        if len(components) < 2:
            continue
        grouped[var.family].append((var.name, components))

    families: list[_Family] = []
    for name, members in grouped.items():
        arities = {len(c) for _, c in members}
        if len(arities) != 1:
            # Mixed arity within one family is a parse we should not trust: its
            # edges would not all mean the same thing.
            continue
        families.append(
            _Family(
                name=name,
                members=members,
                sources={c[0] for _, c in members},
                targets={c[1] for _, c in members},
                arity=arities.pop(),
                discrete=all(
                    types.get(n) in (VariableType.BINARY, VariableType.INTEGER) for n, _ in members
                ),
            )
        )
    return families


def _choose_edge_families(
    families: list[_Family],
    solution: dict[str, float],
    types: dict[str, VariableType],
) -> list[_Family]:
    """Pick the families that genuinely describe ONE graph — and no others.

    Being indexed by two labels does not make a variable an edge. A routing
    model is full of counter-examples: ``s[node, vehicle]`` is an arrival time,
    ``l[node, vehicle]`` a load. Drawing those alongside the real arcs produced
    a picture with "p0 -> 0" arrows in it, which is not a route but a reading of
    the index tuple out loud. Two signals separate the real thing:

    1. **Self-network** — the family's own first two dimensions share labels, so
       it connects nodes to nodes (``x[i, j]``). Decisive on its own.
    2. **Chaining** — one family's targets are another's sources, which is how a
       multi-layer formulation spells a path: the owner's TFM writes
       start->load, load->unload, unload->end as three separate families, and
       none of them is self-network. Chaining is restricted to DISCRETE families
       so an arrival time cannot chain onto the arcs that reach its node.

    Families are then grouped into connected components and the busiest one
    wins, because a model can contain more than one unrelated relation and
    overlaying them says nothing true about either.

    Bipartite assignments (``assign[worker, task]``) are neither self-network nor
    chained, so they are admitted only as a fallback, and only when binary — a
    single yes/no decision per pair is what makes a matching a matching.
    """
    if not families:
        return []

    def active_count(family: _Family) -> int:
        total = 0
        for name, _ in family.members:
            value = solution.get(name)
            if value is None:
                continue
            discrete = types.get(name) in (VariableType.BINARY, VariableType.INTEGER)
            if abs(value) >= (_ACTIVE_EPS if discrete else _NONZERO_EPS):
                total += 1
        return total

    linkable = [f for f in families if f.is_self_network or f.discrete]
    components = _connected_components(linkable)

    # Labels that the real edge families use as a GROUP (their third and later
    # dimensions) are resources — vehicles, periods, machines. A family whose
    # targets are drawn from that pool is indexed BY a resource, not pointing at
    # one: "break[node, vehicle]" is binary and two-index like a matching, and
    # would otherwise sneak in as one. Only meaningful once we know which
    # families are genuinely edges, hence the two passes.
    resource_labels: set[str] = set()
    for component in components:
        if len(component) > 1 or component[0].is_self_network:
            for family in component:
                for _, components_of in family.members:
                    resource_labels.update(components_of[2:])

    def stands_alone(family: _Family) -> bool:
        if family.is_self_network:
            return True
        # A matching needs a yes/no decision per pair, and must not be pointing
        # at a resource.
        return family.discrete and not (family.targets & resource_labels)

    candidates = [
        component for component in components if len(component) > 1 or stands_alone(component[0])
    ]
    if not candidates:
        return []

    best = max(candidates, key=lambda component: sum(active_count(f) for f in component))
    return best if sum(active_count(f) for f in best) else []


def _connected_components(families: list[_Family]) -> list[list[_Family]]:
    """Group families that hand off to each other (targets of one = sources of another)."""
    parent = list(range(len(families)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, first in enumerate(families):
        for j in range(i + 1, len(families)):
            second = families[j]
            if (first.targets & second.sources) or (second.targets & first.sources):
                union(i, j)

    grouped: dict[int, list[_Family]] = defaultdict(list)
    for index, family in enumerate(families):
        grouped[find(index)].append(family)
    return list(grouped.values())


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

    types = {v.name: v.type for v in problem.variables}
    families = _collect_families(problem, types)
    chosen = _choose_edge_families(families, solution, types)
    if not chosen:
        return None

    graph = SolutionGraph()
    seen_groups: dict[str, None] = {}
    edges: list[GraphEdge] = []

    for family in sorted(chosen, key=lambda f: f.name):
        members = family.members
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
                    family=family.name,
                )
            )
            if group is not None:
                seen_groups.setdefault(group, None)
            family_used = True
        if family_used:
            graph.families.append(family.name)

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
