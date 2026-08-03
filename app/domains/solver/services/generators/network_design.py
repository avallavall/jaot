"""Survivable network design — pick edges so the network survives a link failure.

Minimum-cost selection from a candidate edge set such that every node is
connected to the root by ``min_paths`` edge-disjoint paths (default 2 — the
graph stays connected if any single link fails). Edge connectivity is a
pairwise-minimum, so root-to-all disjoint paths certify it for every pair.

Formulation: one commodity per non-root node. For fixed edge choices, pushing
``min_paths`` units with a per-edge capacity of 1 (both directions combined)
is feasible exactly when that many edge-disjoint paths exist (max-flow /
min-cut), so the flows can stay continuous — only the edges are binary.
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


class NetworkDesignGenerator(BaseGenerator):
    """Generate minimum-cost survivable (k-edge-connected) network designs."""

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        edges_raw = find_list_field(
            user_input, ["candidate_edges", "edges", "links"], fallback=False
        )
        if not edges_raw:
            raise ValueError(
                f"Network design requires a candidate_edges list. "
                f"Got keys: {list(user_input.keys())}"
            )
        min_paths = int(user_input.get("min_paths", 2))

        nodes_raw = find_list_field(user_input, ["nodes"], fallback=False)
        node_names: list[str] = [
            self.sanitize_name(str(n.get("name", n.get("id", "")))) for n in nodes_raw
        ]

        edges: list[tuple[str, str, float]] = []
        for e in edges_raw:
            u = self.sanitize_name(str(e.get("from_node", e.get("from", e.get("source", "")))))
            v = self.sanitize_name(str(e.get("to_node", e.get("to", e.get("target", "")))))
            cost = float(e.get("cost", e.get("installation_cost", 1)))
            if u and v and u != v:
                edges.append((u, v, cost))
        if not node_names:
            seen: list[str] = []
            for u, v, _ in edges:
                for name in (u, v):
                    if name not in seen:
                        seen.append(name)
            node_names = seen
        if len(node_names) < 2:
            raise ValueError("Network design requires at least 2 nodes.")

        root = node_names[0]
        terminals = [n for n in node_names[1:]]

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        cost_terms: list[str] = []

        edge_var: dict[tuple[str, str], str] = {}
        for u, v, cost in edges:
            name = f"e_{u}_{v}"
            if (u, v) in edge_var:
                continue  # parallel duplicates collapse; the cheaper listing came first
            edge_var[(u, v)] = name
            variables.append(Variable(name=name, type=VariableType.BINARY))
            cost_terms.append(f"{cost}*{name}")

        # One commodity per terminal: min_paths units root -> terminal, each
        # selected edge carrying at most one unit (both directions combined),
        # which is exactly "min_paths edge-disjoint paths".
        for t in terminals:
            for (u, v), e_name in edge_var.items():
                f_uv = f"f_{t}_{u}_{v}"
                f_vu = f"f_{t}_{v}_{u}"
                variables.append(
                    Variable(name=f_uv, type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=1)
                )
                variables.append(
                    Variable(name=f_vu, type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=1)
                )
                constraints.append(
                    Constraint(
                        name=f"cap_{t}_{u}_{v}",
                        expression=f"{f_uv} + {f_vu} - {e_name} <= 0",
                    )
                )

            for node in node_names:
                out_terms: list[str] = []
                in_terms: list[str] = []
                for u, v in edge_var:
                    if u == node:
                        out_terms.append(f"f_{t}_{u}_{v}")
                        in_terms.append(f"f_{t}_{v}_{u}")
                    elif v == node:
                        out_terms.append(f"f_{t}_{v}_{u}")
                        in_terms.append(f"f_{t}_{u}_{v}")
                if not out_terms and not in_terms:
                    continue
                all_terms = out_terms + [f"-1*{term}" for term in in_terms]
                if node == root:
                    rhs = min_paths
                elif node == t:
                    rhs = -min_paths
                else:
                    rhs = 0
                constraints.append(
                    Constraint(
                        name=f"flow_{t}_{node}",
                        expression=f"{' + '.join(all_terms)} == {rhs}",
                    )
                )

        return OptimizationProblem(
            name="network_design",
            description=(
                f"Select edges so every node has {min_paths} edge-disjoint paths "
                f"to {root} at minimum cost ({len(node_names)} nodes, "
                f"{len(edge_var)} candidate edges)"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
