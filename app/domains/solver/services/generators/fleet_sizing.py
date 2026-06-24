"""Fleet sizing generator — fleet composition optimization.

Determines the optimal number of each vehicle type to meet total demand
at minimum cost, respecting availability and operational constraints.
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


class FleetSizingGenerator(BaseGenerator):
    """Generate fleet sizing problems.

    Input: vehicle types with capacity/cost, demand to satisfy.
    Output: integer quantities per vehicle type, minimize total cost.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        vehicle_types = find_list_field(
            user_input, ["vehicle_types", "vehicles", "fleet", "assets"]
        )
        if not vehicle_types:
            raise ValueError(
                f"Fleet sizing requires vehicle_types list. Got keys: {list(user_input.keys())}"
            )

        # Total demand — scalar or sum of demand segments
        demand_segments = user_input.get("demand_segments", [])
        if demand_segments:
            total_demand = sum(
                float(s.get("daily_parcels", s.get("demand", s.get("volume", 0))))
                for s in demand_segments
            )
        else:
            total_demand = float(user_input.get("total_demand", user_input.get("demand", 0)))

        # Optional per-type overrides
        min_by_type = user_input.get("min_vehicles_by_type", user_input.get("constraints", {}))
        max_by_type = user_input.get("max_vehicles_by_type", {})

        variables: list[Variable] = []
        cost_terms: list[str] = []
        capacity_terms: list[str] = []

        for vt in vehicle_types:
            name = self.sanitize_name(vt.get("name", f"vehicle_{len(variables)}"))
            capacity = float(vt.get("capacity_parcels", vt.get("capacity", vt.get("units", 1))))
            cost = float(vt.get("daily_fixed_cost", vt.get("cost", vt.get("fixed_cost", 1))))
            max_avail = vt.get("max_available", vt.get("max_units", None))

            lower = 0
            upper = max_avail
            if isinstance(min_by_type, dict) and vt.get("name") in min_by_type:
                lower = int(min_by_type[vt["name"]])
            if isinstance(max_by_type, dict) and vt.get("name") in max_by_type:
                upper = int(max_by_type[vt["name"]])

            variables.append(
                Variable(name=name, type=VariableType.INTEGER, lower_bound=lower, upper_bound=upper)
            )
            cost_terms.append(f"{cost}*{name}")
            capacity_terms.append(f"{capacity}*{name}")

        constraints: list[Constraint] = []

        # Total capacity must meet demand
        if total_demand > 0:
            constraints.append(
                Constraint(
                    name="demand_coverage",
                    expression=f"{' + '.join(capacity_terms)} >= {total_demand}",
                )
            )

        return OptimizationProblem(
            name="fleet_sizing",
            description=f"Size fleet of {len(vehicle_types)} vehicle types to meet demand {total_demand}",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
