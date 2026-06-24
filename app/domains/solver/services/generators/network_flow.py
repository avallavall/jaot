"""Network flow generator — min-cost flow and max-flow problems.

Supports domain-specific input formats (pipelines, pipes, routes, etc.)
by auto-detecting nodes and arcs/edges from the input dict.
"""

from typing import Any, cast

from app.domains.solver.services.generators.base import BaseGenerator
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class NetworkFlowGenerator(BaseGenerator):
    """Generate min-cost network flow problems.

    Nodes have supply (positive) or demand (negative). Arcs have cost and capacity.
    Flow conservation at each node.
    """

    @staticmethod
    def _find_preferred(user_input: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
        """Find a list-of-dicts field using only the specified keys (no fallback)."""
        for key in keys:
            if key in user_input and isinstance(user_input[key], list):
                return cast(list[dict[str, Any]], user_input[key])
        return []

    def _normalize_arcs(
        self, arcs_raw: list[dict[str, Any]], arc_field_hints: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Normalize arc dicts to standard {from, to, cost, capacity} format."""
        normalized = []
        for arc in arcs_raw:
            # Auto-detect from/to fields
            from_node = (
                arc.get("from")
                or arc.get("from_node")
                or arc.get("from_depot")
                or arc.get("source")
                or arc.get("origin")
                or arc.get("start")
                or ""
            )
            to_node = (
                arc.get("to")
                or arc.get("to_node")
                or arc.get("to_mill")
                or arc.get("destination")
                or arc.get("target")
                or arc.get("end")
                or arc.get("sink")
                or ""
            )
            cost = arc.get("cost", arc.get("cost_per_unit", arc.get("price", 1)))
            capacity = arc.get("capacity", arc.get("max_flow", None))
            normalized.append(
                {
                    "from": str(from_node),
                    "to": str(to_node),
                    "cost": cost,
                    "capacity": capacity,
                }
            )
        return normalized

    def _build_arcs_from_two_lists(
        self,
        sources: list[dict[str, Any]],
        sinks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build nodes and arcs when input has separate source/sink lists."""
        nodes: list[dict[str, Any]] = []
        arcs: list[dict[str, Any]] = []
        for s in sources:
            s_name = s.get("name", s.get("id", f"src_{len(nodes)}"))
            supply = s.get(
                "supply", s.get("capacity", s.get("production", s.get("flow_volume", 10)))
            )
            nodes.append({"name": s_name, "supply": supply})

        for d in sinks:
            d_name = d.get("name", d.get("id", f"sink_{len(nodes)}"))
            demand = d.get("demand", d.get("capacity", d.get("required", d.get("flow_volume", 10))))
            nodes.append({"name": d_name, "supply": -demand})

        for s in sources:
            s_name = s.get("name", "")
            for d in sinks:
                d_name = d.get("name", "")
                cost = 1  # default cost
                arcs.append({"from": s_name, "to": d_name, "cost": cost, "capacity": None})

        return nodes, arcs

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        _NODE_KEYS = ["nodes"]
        _ARC_KEYS = [
            "arcs",
            "edges",
            "pipelines",
            "pipes",
            "routes",
            "candidate_edges",
            "links",
            "connections",
        ]

        # Only use preferred keys (no fallback) so we don't accidentally merge lists
        nodes_raw = self._find_preferred(user_input, _NODE_KEYS)
        arcs_raw = self._find_preferred(user_input, _ARC_KEYS)

        # Determine nodes and arcs from the input
        if nodes_raw and arcs_raw:
            # Both found via preferred keys
            nodes = nodes_raw
            arcs = self._normalize_arcs(arcs_raw)
        elif nodes_raw and not arcs_raw:
            # Nodes found, but no recognized arc keys -- look for other lists
            other_lists = [
                (k, v)
                for k, v in user_input.items()
                if isinstance(v, list) and v and isinstance(v[0], dict) and k not in _NODE_KEYS
            ]
            if other_lists:
                arcs = self._normalize_arcs(other_lists[0][1])
                nodes = nodes_raw
            else:
                raise ValueError(
                    f"Network flow generator found nodes but no arcs/edges. "
                    f"Got keys: {list(user_input.keys())}"
                )
        elif arcs_raw and not nodes_raw:
            # Arcs found but no nodes — derive nodes from arc endpoints
            arcs = self._normalize_arcs(arcs_raw)
            node_set: set[str] = set()
            for arc in arcs:
                node_set.add(arc["from"])
                node_set.add(arc["to"])
            nodes = [{"name": n, "supply": 0} for n in sorted(node_set)]
        else:
            # No preferred keys matched -- auto-detect from all lists
            all_lists = [
                (k, v)
                for k, v in user_input.items()
                if isinstance(v, list) and v and isinstance(v[0], dict)
            ]

            # Check if any list looks like arcs (has from/to-like keys)
            arc_like = None
            non_arc_lists = []
            for k, lst in all_lists:
                first = lst[0]
                has_from_to = any(
                    key in first
                    for key in [
                        "from",
                        "to",
                        "from_node",
                        "to_node",
                        "source",
                        "destination",
                        "from_depot",
                        "to_mill",
                    ]
                )
                if has_from_to:
                    arc_like = (k, lst)
                else:
                    non_arc_lists.append((k, lst))

            if arc_like and non_arc_lists:
                all_source_nodes: list[dict[str, Any]] = []
                for _, lst in non_arc_lists:
                    for item in lst:
                        name = item.get("name", item.get("id", ""))
                        supply = item.get("supply", 0)
                        demand = item.get("demand", 0)
                        all_source_nodes.append({"name": name, "supply": supply - demand})
                nodes = all_source_nodes
                arcs = self._normalize_arcs(arc_like[1])
            elif len(non_arc_lists) >= 2:
                # Two-list format (sources + sinks)
                nodes, arcs = self._build_arcs_from_two_lists(
                    non_arc_lists[0][1], non_arc_lists[1][1]
                )
            else:
                raise ValueError(
                    f"Network flow generator requires nodes+arcs or source+sink lists. "
                    f"Got keys: {list(user_input.keys())}"
                )

        variables: list[Variable] = []
        cost_terms: list[str] = []

        node_names = [
            self.sanitize_name(n.get("name", n.get("id", f"n_{i}"))) for i, n in enumerate(nodes)
        ]
        node_supply = {}
        for i, n in enumerate(nodes):
            name = self.sanitize_name(n.get("name", n.get("id", f"n_{i}")))
            supply = n.get("supply", 0)
            demand = n.get("demand", 0)
            # Demand nodes have negative supply
            node_supply[name] = supply - demand

        # Flow variable for each arc (de-duplicate names for parallel arcs)
        seen_var_names: set[str] = set()
        for arc_idx, arc in enumerate(arcs):
            from_name = self.sanitize_name(arc.get("from", ""))
            to_name = self.sanitize_name(arc.get("to", ""))
            var_name = f"f_{from_name}_{to_name}"
            if var_name in seen_var_names:
                var_name = f"f_{from_name}_{to_name}_{arc_idx}"
            seen_var_names.add(var_name)
            arc["_var_name"] = var_name
            capacity = arc.get("capacity", None)
            cost = arc.get("cost", 1)

            variables.append(
                Variable(
                    name=var_name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=capacity,
                )
            )
            cost_terms.append(f"{cost}*{var_name}")

        if not variables:
            raise ValueError(
                "Network flow generator produced no flow variables. "
                "Check that arcs connect valid nodes."
            )

        constraints: list[Constraint] = []

        # Flow conservation at each node
        for node_name in node_names:
            supply = node_supply.get(node_name, 0)

            in_terms: list[str] = []
            out_terms: list[str] = []

            for arc in arcs:
                from_name = self.sanitize_name(arc.get("from", ""))
                to_name = self.sanitize_name(arc.get("to", ""))
                var_name = arc.get("_var_name", f"f_{from_name}_{to_name}")

                if to_name == node_name:
                    in_terms.append(var_name)
                if from_name == node_name:
                    out_terms.append(var_name)

            # out - in == supply
            parts: list[str] = []
            if out_terms:
                parts.append(" + ".join(out_terms))
            if in_terms:
                if parts:
                    parts.append(f" - {' - '.join(in_terms)}")
                else:
                    parts.append(f"-1*{' + -1*'.join(in_terms)}")

            if parts:
                expr = "".join(parts)
                constraints.append(
                    Constraint(
                        name=f"flow_{node_name}",
                        expression=f"{expr} == {supply}",
                    )
                )

        return OptimizationProblem(
            name="network_flow",
            description=f"Min-cost flow on {len(nodes)} nodes, {len(arcs)} arcs",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
