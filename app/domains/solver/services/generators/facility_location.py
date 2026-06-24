"""Facility location generator — p-median and capacitated facility location problems."""

from typing import Any

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


class FacilityLocationGenerator(BaseGenerator):
    """Generate capacitated facility location problems.

    Decide which facilities to open and how to assign customers,
    minimizing fixed costs + transport costs while meeting demand.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        facilities = user_input.get(
            "facilities",
            user_input.get("candidate_sites", []),
        )
        customers = user_input.get(
            "customers",
            user_input.get("communities", user_input.get("demand_zones", [])),
        )
        transport_costs = user_input.get("transport_costs", {})

        variables: list[Variable] = []
        cost_terms: list[str] = []
        constraints: list[Constraint] = []

        # y_f: binary, 1 if facility f is open
        fac_names: list[str] = []
        for f in facilities:
            f_name = self.sanitize_name(f.get("name", f"f_{len(fac_names)}"))
            fixed_cost = f.get("fixed_cost", 0)
            fac_names.append(f_name)

            variables.append(Variable(name=f"open_{f_name}", type=VariableType.BINARY))
            cost_terms.append(f"{fixed_cost}*open_{f_name}")

        # x_f_c: continuous, fraction of customer c demand served by facility f
        cust_names: list[str] = []
        for c in customers:
            c_name = self.sanitize_name(c.get("name", f"c_{len(cust_names)}"))
            demand = c.get("demand", 1)
            cust_names.append(c_name)

            assign_vars: list[str] = []
            for f_name in fac_names:
                var_name = f"x_{f_name}_{c_name}"
                t_cost = transport_costs.get(f"{f_name}_{c_name}", 100)

                variables.append(
                    Variable(
                        name=var_name,
                        type=VariableType.CONTINUOUS,
                        lower_bound=0,
                        upper_bound=1,
                    )
                )
                cost_terms.append(f"{t_cost * demand}*{var_name}")
                assign_vars.append(var_name)

            # Demand satisfaction: each customer fully served
            constraints.append(
                Constraint(
                    name=f"demand_{c_name}",
                    expression=f"{' + '.join(assign_vars)} == 1",
                )
            )

        # Capacity constraints: can only serve from open facilities
        for i, f in enumerate(facilities):
            f_name = fac_names[i]
            capacity = f.get("capacity", 1000)

            cap_terms: list[str] = []
            for j, c in enumerate(customers):
                c_name = cust_names[j]
                demand = c.get("demand", 1)
                cap_terms.append(f"{demand}*x_{f_name}_{c_name}")

            constraints.append(
                Constraint(
                    name=f"capacity_{f_name}",
                    expression=f"{' + '.join(cap_terms)} - {capacity}*open_{f_name} <= 0",
                )
            )

        # Max facilities constraint (p-median)
        max_facilities = user_input.get("max_facilities")
        if max_facilities is not None and max_facilities > 0:
            open_vars = [f"open_{f_name}" for f_name in fac_names]
            constraints.append(
                Constraint(
                    name="max_facilities",
                    expression=f"{' + '.join(open_vars)} <= {max_facilities}",
                )
            )

        return OptimizationProblem(
            name="facility_location",
            description=(
                f"Locate {len(facilities)} facilities to serve {len(customers)} customers"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
