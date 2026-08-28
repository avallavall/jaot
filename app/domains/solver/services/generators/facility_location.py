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

    #: Cards name a facility with either key, and the customer's cost map is
    #: keyed by whichever one the facility row used.
    _FACILITY_ID_KEYS = ("name", "id", "site", "code")
    _FIXED_COST_KEYS = ("fixed_cost", "opening_cost", "cost", "setup_cost")
    _DEMAND_KEYS = ("demand", "population", "volume", "units")

    @classmethod
    def _row_id(cls, row: dict[str, Any]) -> str | None:
        for key in cls._FACILITY_ID_KEYS:
            value = row.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if row.get(key) is not None:
                return float(row[key])
        return None

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        facilities = user_input.get(
            "facilities",
            user_input.get("candidate_sites", []),
        )
        customers = user_input.get(
            "customers",
            user_input.get("communities", user_input.get("demand_zones", [])),
        )
        if not facilities or not customers:
            raise ValueError(
                "Facility location needs a facilities list and a customers list. "
                f"Got keys: {list(user_input.keys())}"
            )

        variables: list[Variable] = []
        cost_terms: list[str] = []
        constraints: list[Constraint] = []

        # y_f: binary, 1 if facility f is open
        fac_names: list[str] = []
        for i, f in enumerate(facilities):
            raw_id = self._row_id(f) or f"f_{i}"
            f_name = self.sanitize_name(raw_id)
            fixed_cost = self._pick(f, self._FIXED_COST_KEYS)
            if fixed_cost is None:
                raise ValueError(
                    f"Facility '{raw_id}' states no opening cost. "
                    f"Expected one of: {', '.join(self._FIXED_COST_KEYS)}."
                )
            fac_names.append(f_name)

            variables.append(Variable(name=f"open_{f_name}", type=VariableType.BINARY))
            cost_terms.append(f"{fixed_cost}*open_{f_name}")

        # A flat table keyed "<facility>_<customer>" is one layout; a per-
        # customer map is the other. Reading only the first meant three cards
        # priced every route at a hardcoded 100 and threw their whole cost
        # matrix away.
        flat_costs = {
            self.sanitize_name(k): v for k, v in (user_input.get("transport_costs") or {}).items()
        }

        # x_f_c: continuous, fraction of customer c demand served by facility f
        cust_names: list[str] = []
        demands: list[float] = []
        for j, c in enumerate(customers):
            raw_c = self._row_id(c) or f"c_{j}"
            c_name = self.sanitize_name(raw_c)
            demand = self._pick(c, self._DEMAND_KEYS)
            if demand is None:
                raise ValueError(
                    f"Customer '{raw_c}' states no demand. "
                    f"Expected one of: {', '.join(self._DEMAND_KEYS)}."
                )
            cust_names.append(c_name)
            demands.append(demand)
            own_costs = {self.sanitize_name(k): v for k, v in (c.get("costs") or {}).items()}

            assign_vars: list[str] = []
            for f_name in fac_names:
                var_name = f"x_{f_name}_{c_name}"
                if f_name in own_costs:
                    t_cost = float(own_costs[f_name])
                elif f"{f_name}_{c_name}" in flat_costs:
                    t_cost = float(flat_costs[f"{f_name}_{c_name}"])
                else:
                    raise ValueError(
                        f"No transport cost for facility '{f_name}' to customer '{raw_c}'. "
                        "Give each customer a 'costs' map keyed by facility, or a top-level "
                        "'transport_costs' keyed '<facility>_<customer>'."
                    )

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

        # Capacity constraints: can only serve from open facilities. Without a
        # stated capacity the facility is uncapacitated, so the row only has to
        # stop it serving while closed; inventing a limit of 1000 silently
        # capped cards whose units were people or pallets.
        for i, f in enumerate(facilities):
            f_name = fac_names[i]
            capacity = self._pick(f, ("capacity", "max_capacity", "throughput"))
            limit = capacity if capacity is not None else sum(demands)

            cap_terms = [f"{demands[j]}*x_{f_name}_{cust_names[j]}" for j in range(len(customers))]
            constraints.append(
                Constraint(
                    name=f"capacity_{f_name}",
                    expression=f"{' + '.join(cap_terms)} - {limit}*open_{f_name} <= 0",
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
