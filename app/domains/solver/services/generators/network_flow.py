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
            cost = arc.get(
                "cost",
                arc.get(
                    "cost_per_unit",
                    arc.get("cost_per_m3", arc.get("unit_cost", arc.get("price", 1))),
                ),
            )
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
                "supply",
                s.get(
                    "capacity",
                    s.get("production", s.get("loading_rate_tph", s.get("flow_volume", 10))),
                ),
            )
            nodes.append({"name": s_name, "supply": supply})

        for d in sinks:
            d_name = d.get("name", d.get("id", f"sink_{len(nodes)}"))
            # A plant's capacity is how much it CAN take, not how much it must.
            # Reading it as a demand forced every plant to run full, so the
            # example only worked because someone had tuned total capacity to
            # equal total flow, and giving the network any slack made it
            # infeasible.
            stated_demand = next(
                (d[k] for k in ("demand", "required", "flow_volume") if d.get(k) is not None),
                None,
            )
            ceiling = next(
                (
                    d[k]
                    for k in ("capacity", "capacity_tph", "max_capacity")
                    if d.get(k) is not None
                ),
                None,
            )
            nodes.append(
                {
                    "name": d_name,
                    "supply": -(stated_demand if stated_demand is not None else (ceiling or 10)),
                    "ceiling_only": stated_demand is None and ceiling is not None,
                }
            )

        # What it costs to send a unit down this arc. A flat 1 makes every route
        # cost the same, so the objective is the total flow again and any
        # routing ties for "optimal" — which is what wastewater_treatment_
        # allocation was doing while its plants each stated a price per unit.
        _COST_KEYS = ("cost_per_unit", "processing_cost", "unit_cost", "cost", "price_per_unit")
        for s in sources:
            s_name = s.get("name", "")
            s_cost = next((float(s[k]) for k in _COST_KEYS if s.get(k) is not None), 0.0)
            for d in sinks:
                d_name = d.get("name", "")
                d_cost = next((float(d[k]) for k in _COST_KEYS if d.get(k) is not None), 0.0)
                cost = s_cost + d_cost
                if cost == 0:
                    cost = 1
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
            # Arcs found under a preferred key, but no "nodes" list. The other
            # lists in the input are the nodes: throwing them away and deriving
            # zero-supply nodes from the arc endpoints — what this branch did —
            # zeroed every supply and demand, so the optimal flow was "move
            # nothing" (measured: the timber card answered cost 0).
            arcs = self._normalize_arcs(arcs_raw)
            arc_key = next(k for k in _ARC_KEYS if k in user_input)
            other_lists = [
                v
                for k, v in user_input.items()
                if k != arc_key and isinstance(v, list) and v and isinstance(v[0], dict)
            ]
            nodes = [
                {
                    "name": item.get("name", item.get("id", "")),
                    "supply": item.get("supply", 0) - item.get("demand", 0),
                }
                for lst in other_lists
                for item in lst
                if item.get("name", item.get("id"))
            ]
            named = {self.sanitize_name(str(n["name"])) for n in nodes}
            # Endpoints not described by any list are transshipment nodes.
            node_set: set[str] = set()
            for arc in arcs:
                node_set.add(arc["from"])
                node_set.add(arc["to"])
            nodes.extend(
                {"name": n, "supply": 0}
                for n in sorted(node_set)
                if self.sanitize_name(n) not in named
            )
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

        # A second quantity the flow carries, with its own ceiling. Wastewater
        # leaving a plant is the flow times how dirty it arrived times how much
        # the plant fails to remove; the card promises a discharge limit and
        # nothing was writing one, so contamination and efficiency sat in the
        # input doing nothing.
        arc_limit = params.get("arc_limit")
        if arc_limit:
            by_name = {
                str(row.get("name", row.get("id", ""))): row
                for group in ("sources", "plants", "nodes", "sinks")
                for row in (user_input.get(group) or [])
                if isinstance(row, dict)
            }
            from_field = arc_limit["from_field"]
            to_complement = arc_limit.get("to_complement")
            ceiling = user_input.get(arc_limit["max_field"])
            if ceiling is None:
                raise ValueError(f"Input states no '{arc_limit['max_field']}' to cap the arcs.")
            terms = []
            for arc in arcs:
                head = by_name.get(str(arc.get("from", "")))
                tail = by_name.get(str(arc.get("to", "")))
                if head is None or head.get(from_field) is None:
                    continue
                weight = float(head[from_field])
                if to_complement and tail is not None and tail.get(to_complement) is not None:
                    weight *= 1 - float(tail[to_complement])
                terms.append(f"{round(weight, 6)}*{arc['_var_name']}")
            if not terms:
                raise ValueError(f"arc_limit names '{from_field}' but no arc head carries it.")
            constraints.append(
                Constraint(
                    name=arc_limit.get("name", "arc_limit"),
                    expression=f"{' + '.join(terms)} <= {float(ceiling)}",
                )
            )

        # mode="max_flow" (template param): maximize the flow reaching the
        # sinks instead of forcing pre-computed supplies through at min cost.
        # The shipped max-flow card had zero costs and supplies equal to the
        # known answer, so the model merely VERIFIED a flow of that value and
        # reported an optimal cost of 0 — the objective now IS the flow value,
        # and a node's supply/demand acts as a bound, not a requirement.
        max_flow_mode = params.get("mode") == "max_flow"

        # With more supply than demand, sources may keep their surplus (the
        # transportation convention): out - in <= supply there, while demand
        # rows stay hard. Equality everywhere made ANY unbalanced instance
        # infeasible outright. Balanced instances are unaffected — the demand
        # rows pull every supply row tight.
        total_pos = sum(s for s in node_supply.values() if s > 0)
        total_neg = -sum(s for s in node_supply.values() if s < 0)
        relax_supply_rows = total_pos > total_neg
        ceiling_only = {
            self.sanitize_name(str(n.get("name", n.get("id", ""))))
            for n in nodes
            if isinstance(n, dict) and n.get("ceiling_only")
        }

        # Flow conservation at each node
        sink_inflow_terms: list[str] = []
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

            if not parts:
                continue
            expr = "".join(parts)

            if max_flow_mode:
                # Sources push what they can, sinks absorb what arrives; the
                # stated supply/demand caps the node instead of dictating it.
                # Intermediates conserve exactly.
                if supply > 0:
                    constraints.append(
                        Constraint(name=f"flow_{node_name}", expression=f"{expr} <= {supply}")
                    )
                elif supply < 0:
                    sink_inflow_terms.extend(in_terms)
                    constraints.append(
                        Constraint(name=f"flow_{node_name}", expression=f"{expr} >= {supply}")
                    )
                else:
                    constraints.append(
                        Constraint(name=f"flow_{node_name}", expression=f"{expr} == 0")
                    )
                continue

            if node_name in ceiling_only:
                # out - in >= -capacity, i.e. this node absorbs at most its
                # capacity. The supply figure is negative, so the direction
                # reads backwards from "at most".
                op = ">="
            elif relax_supply_rows and supply > 0:
                op = "<="
            else:
                op = "=="
            constraints.append(
                Constraint(
                    name=f"flow_{node_name}",
                    expression=f"{expr} {op} {supply}",
                )
            )

        if max_flow_mode:
            if not sink_inflow_terms:
                raise ValueError(
                    "max_flow mode needs at least one sink node (negative supply or a demand)."
                )
            return OptimizationProblem(
                name="max_flow",
                description=f"Maximum flow on {len(nodes)} nodes, {len(arcs)} arcs",
                variables=variables,
                objective=Objective(
                    sense=ObjectiveSense.MAXIMIZE,
                    expression=" + ".join(sink_inflow_terms),
                ),
                constraints=constraints,
                options=SolverOptions(time_limit_seconds=60),
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
