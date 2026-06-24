"""Routing generator — vehicle routing problems (CVRP) with MTZ subtour elimination.

Supports domain-specific input formats by auto-detecting locations, vehicles,
depot, and distances from the input dict.

Pre-optimization (Pilar 2.5):
- Symmetry breaking for identical vehicles
- Greedy nearest-neighbor warm start
"""

from typing import Any

from app.domains.solver.services.generators.base import (
    BaseGenerator,
    add_symmetry_breaking,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class RoutingGenerator(BaseGenerator):
    """Generate capacitated vehicle routing problems (CVRP).

    Uses Miller-Tucker-Zemlin (MTZ) subtour elimination formulation.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        locations = user_input.get("locations", user_input.get("destinations", []))
        vehicles = user_input.get("vehicles", [])
        distances = user_input.get("distances", {})

        depot = user_input.get("depot", None)
        if depot is None:
            warehouses = user_input.get("warehouses", [])
            depot = warehouses[0] if warehouses else {"name": "depot"}

        if not vehicles:
            vehicles = [{"name": "v0", "capacity": 1000, "cost_per_unit_distance": 1.0}]

        # Normalize distances: support list-of-dicts format
        if isinstance(distances, list):
            dist_dict: dict[str, float] = {}
            for d in distances:
                from_loc = self.sanitize_name(str(d.get("from_loc", d.get("from", ""))))
                to_loc = self.sanitize_name(str(d.get("to_loc", d.get("to", ""))))
                dist_dict[f"{from_loc}_{to_loc}"] = d.get("distance", d.get("cost", 100))
            distances = dist_dict

        depot_name = self.sanitize_name(depot.get("name", "depot"))
        loc_names = [
            self.sanitize_name(loc.get("name", f"loc_{i}")) for i, loc in enumerate(locations)
        ]
        loc_names = [n for n in loc_names if n != depot_name]
        all_nodes = [depot_name] + loc_names
        n_vehicles = len(vehicles)

        variables: list[Variable] = []
        cost_terms: list[str] = []
        constraints: list[Constraint] = []

        # Vehicle name lookup
        v_names = [self.sanitize_name(veh.get("name", f"v{i}")) for i, veh in enumerate(vehicles)]

        # x_{v}_{i}_{j} = 1 if vehicle v travels from i to j
        # Precompute distances once (not per vehicle)
        dist_lookup: dict[tuple[str, str], float] = {
            (i, j): distances.get(f"{i}_{j}", 100) for i in all_nodes for j in all_nodes if i != j
        }

        x_vars: dict[tuple[str, str, str], str] = {}
        for v_idx, veh in enumerate(vehicles):
            v_name = v_names[v_idx]
            cost_mult = veh.get("cost_per_unit_distance", 1.0)

            for i_name in all_nodes:
                for j_name in all_nodes:
                    if i_name == j_name:
                        continue
                    var_name = f"x_{v_name}_{i_name}_{j_name}"
                    variables.append(Variable(name=var_name, type=VariableType.BINARY))
                    x_vars[(v_name, i_name, j_name)] = var_name
                    cost_terms.append(f"{dist_lookup[(i_name, j_name)] * cost_mult}*{var_name}")

        # MTZ subtour elimination variables
        demands: dict[str, float] = {}
        for i, loc_name in enumerate(loc_names):
            demand_raw = locations[i].get("demand", 1)
            demand = sum(demand_raw.values()) if isinstance(demand_raw, dict) else demand_raw
            demands[loc_name] = demand
            max_cap = max(veh.get("capacity", 100) for veh in vehicles)
            variables.append(
                Variable(
                    name=f"u_{loc_name}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=demand,
                    upper_bound=max_cap,
                )
            )

        # Each customer visited exactly once
        for j_name in loc_names:
            visit_vars = [
                x_vars[(v_name, i_name, j_name)]
                for v_name in v_names
                for i_name in all_nodes
                if i_name != j_name and (v_name, i_name, j_name) in x_vars
            ]
            constraints.append(
                Constraint(name=f"visit_{j_name}", expression=f"{' + '.join(visit_vars)} == 1")
            )

        # Flow conservation (in - out = 0)
        for v_name in v_names:
            for k_name in loc_names:
                in_terms = [
                    x_vars[(v_name, i, k_name)]
                    for i in all_nodes
                    if i != k_name and (v_name, i, k_name) in x_vars
                ]
                out_terms = [
                    f"-1*{x_vars[(v_name, k_name, j)]}"
                    for j in all_nodes
                    if j != k_name and (v_name, k_name, j) in x_vars
                ]
                all_terms = in_terms + out_terms
                constraints.append(
                    Constraint(
                        name=f"flow_{v_name}_{k_name}", expression=f"{' + '.join(all_terms)} == 0"
                    )
                )

        # Each vehicle leaves depot at most once
        y_vars: dict[int, str] = {}
        for v_idx, v_name in enumerate(v_names):
            leave_vars = [
                x_vars[(v_name, depot_name, j)]
                for j in loc_names
                if (v_name, depot_name, j) in x_vars
            ]
            y_var = f"y_{v_name}"
            variables.append(Variable(name=y_var, type=VariableType.BINARY))
            y_vars[v_idx] = y_var
            constraints.append(
                Constraint(
                    name=f"depot_leave_{v_name}",
                    expression=f"{' + '.join(leave_vars)} + -1*{y_var} == 0",
                )
            )

        # MTZ capacity constraints
        for v_idx, veh in enumerate(vehicles):
            v_name = v_names[v_idx]
            cap = veh.get("capacity", 100)

            for i_name in loc_names:
                for j_name in loc_names:
                    if i_name == j_name:
                        continue
                    demand_j = demands.get(j_name, 1)
                    constraints.append(
                        Constraint(
                            name=f"mtz_{v_name}_{i_name}_{j_name}",
                            expression=(
                                f"u_{i_name} + -1*u_{j_name} + {cap}*{x_vars[(v_name, i_name, j_name)]}"
                                f" <= {cap - demand_j}"
                            ),
                        )
                    )

        # P4: Symmetry breaking for identical vehicles (same capacity + cost)
        vehicle_groups: dict[tuple[float, float], list[int]] = {}
        for v_idx, veh in enumerate(vehicles):
            key = (veh.get("capacity", 100), veh.get("cost_per_unit_distance", 1.0))
            vehicle_groups.setdefault(key, []).append(v_idx)
        add_symmetry_breaking(constraints, y_vars, list(vehicle_groups.values()))

        # P5: Warm start — nearest-neighbor heuristic
        ws = self._build_nn_warm_start(
            loc_names,
            depot_name,
            v_names,
            vehicles,
            dist_lookup,
            x_vars,
            y_vars,
            demands,
        )

        return OptimizationProblem(
            name="vehicle_routing",
            description=f"Route {n_vehicles} vehicles to {len(loc_names)} locations",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=120),
            heuristic_warm_start=ws,
        )

    @staticmethod
    def _build_nn_warm_start(
        loc_names: list[str],
        depot_name: str,
        v_names: list[str],
        vehicles: list[dict[str, Any]],
        dist_lookup: dict[tuple[str, str], float],
        x_vars: dict[tuple[str, str, str], str],
        y_vars: dict[int, str],
        demands: dict[str, float],
    ) -> dict[str, float] | None:
        """Nearest-neighbor heuristic warm start for CVRP."""
        unvisited = set(loc_names)
        routes: dict[int, list[str]] = {}
        ws: dict[str, float] = {}

        for v_idx, veh in enumerate(vehicles):
            if not unvisited:
                break
            cap = veh.get("capacity", 100)
            route = [depot_name]
            load = 0.0

            while unvisited:
                current = route[-1]
                best_next = None
                best_dist = float("inf")
                for loc in unvisited:
                    d = demands.get(loc, 1)
                    if load + d > cap:
                        continue
                    dist = dist_lookup.get((current, loc), 100)
                    if dist < best_dist:
                        best_dist = dist
                        best_next = loc

                if best_next is None:
                    break
                route.append(best_next)
                load += demands.get(best_next, 1)
                unvisited.discard(best_next)

            route.append(depot_name)
            routes[v_idx] = route

            v_name = v_names[v_idx]
            for pos in range(len(route) - 1):
                xv = x_vars.get((v_name, route[pos], route[pos + 1]))
                if xv:
                    ws[xv] = 1.0

            if y_vars.get(v_idx):
                ws[y_vars[v_idx]] = 1.0 if len(route) > 2 else 0.0

        return ws if ws else None
