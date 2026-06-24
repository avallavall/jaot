"""Spanning tree generator — minimum spanning tree via MIP.

Selects edges to form a connected spanning tree with minimum total cost.
Uses single-commodity flow formulation for connectivity enforcement.
"""

from typing import Any

from app.domains.solver.services.generators.base import BaseGenerator, find_list_field
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class SpanningTreeGenerator(BaseGenerator):
    """Generate minimum spanning tree problems.

    Uses directed single-commodity flow from an arbitrary root to enforce
    connectivity. Each selected undirected edge is modeled as two directed arcs.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        edges = find_list_field(user_input, ["edges", "links", "connections"])
        nodes = find_list_field(user_input, ["nodes", "vertices", "points"])
        if not edges:
            raise ValueError(
                f"Spanning tree requires an edges list. Got keys: {list(user_input.keys())}"
            )

        # Derive node set from edges if not provided
        if not nodes:
            node_set: set[str] = set()
            for e in edges:
                node_set.add(str(e.get("from", e.get("source", ""))))
                node_set.add(str(e.get("to", e.get("target", ""))))
            node_names = sorted(node_set)
        else:
            node_names = [str(n.get("name", n)) if isinstance(n, dict) else str(n) for n in nodes]

        n = len(node_names)
        if n < 2:
            raise ValueError(f"Spanning tree requires at least 2 nodes, got {n}")

        root = self.sanitize_name(node_names[0])

        # Pre-compute sanitized edge endpoints once
        edge_endpoints: list[tuple[str, str, float]] = []
        for e in edges:
            u = self.sanitize_name(str(e.get("from", e.get("source", ""))))
            v = self.sanitize_name(str(e.get("to", e.get("target", ""))))
            cost = float(e.get("cost", e.get("weight", e.get("distance", 1))))
            edge_endpoints.append((u, v, cost))

        variables: list[Variable] = []
        cost_terms: list[str] = []

        for u, v, cost in edge_endpoints:
            variables.append(Variable(name=f"e_{u}_{v}", type=VariableType.BINARY))
            cost_terms.append(f"{cost}*e_{u}_{v}")
            # Directed flow in both directions (undirected edge)
            variables.append(
                Variable(
                    name=f"f_{u}_{v}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=n - 1,
                )
            )
            variables.append(
                Variable(
                    name=f"f_{v}_{u}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=n - 1,
                )
            )

        constraints: list[Constraint] = []

        # Exactly n-1 edges selected
        edge_vars = [f"e_{u}_{v}" for u, v, _ in edge_endpoints]
        constraints.append(
            Constraint(name="tree_size", expression=f"{' + '.join(edge_vars)} == {n - 1}")
        )

        # Flow capacity: flow only on selected edges
        cap = n - 1
        for u, v, _ in edge_endpoints:
            constraints.append(
                Constraint(name=f"cap_{u}_{v}", expression=f"f_{u}_{v} - {cap}*e_{u}_{v} <= 0")
            )
            constraints.append(
                Constraint(name=f"cap_{v}_{u}", expression=f"f_{v}_{u} - {cap}*e_{u}_{v} <= 0")
            )

        # Flow conservation: root sends n-1 units, each other node consumes 1
        san_nodes = [self.sanitize_name(nm) for nm in node_names]
        for node in san_nodes:
            in_terms: list[str] = []
            out_terms: list[str] = []
            for u, v, _ in edge_endpoints:
                if v == node:
                    in_terms.append(f"f_{u}_{v}")
                if u == node:
                    out_terms.append(f"f_{u}_{v}")
                # Reverse-direction arc (undirected edge treated as bidirectional)
                if u == node:
                    in_terms.append(f"f_{v}_{u}")
                if v == node:
                    out_terms.append(f"f_{v}_{u}")

            if not in_terms and not out_terms:
                continue

            if node == root:
                # Root: outflow - inflow = n-1
                all_terms = out_terms + [f"-1*{t}" for t in in_terms]
                constraints.append(
                    Constraint(
                        name=f"flow_{node}",
                        expression=f"{' + '.join(all_terms) if all_terms else '0'} == {n - 1}",
                    )
                )
            else:
                # Non-root: inflow - outflow = 1
                all_terms = in_terms + [f"-1*{t}" for t in out_terms]
                constraints.append(
                    Constraint(
                        name=f"flow_{node}",
                        expression=f"{' + '.join(all_terms) if all_terms else '0'} == 1",
                    )
                )

        return OptimizationProblem(
            name="minimum_spanning_tree",
            description=f"Find MST over {n} nodes and {len(edges)} edges",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
