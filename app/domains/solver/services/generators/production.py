"""Production generator — production planning and budget allocation problems."""

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


class ProductionGenerator(BaseGenerator):
    """Generate production planning problems.

    Also handles budget allocation as a configuration variant
    (continuous variables, budget as resource constraint).
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        products = user_input.get("products", [])
        resources = user_input.get(
            "resources",
            user_input.get("raw_materials", user_input.get("reactors", [])),
        )

        # Handle period-based production/resource allocation (e.g., reservoir operation)
        if not products and "periods" in user_input:
            return self._generate_periodic(user_input, params)

        variables: list[Variable] = []
        profit_terms: list[str] = []

        for p in products:
            name = self.sanitize_name(p.get("name", f"product_{len(variables)}"))
            min_prod = p.get("min_production", 0)
            max_prod = p.get("max_production")
            profit = p.get("profit_per_unit", p.get("price_per_unit", 1))

            variables.append(
                Variable(
                    name=name,
                    type=VariableType.INTEGER
                    if p.get("integer", True)
                    else VariableType.CONTINUOUS,
                    lower_bound=min_prod,
                    upper_bound=max_prod,
                )
            )

            profit_terms.append(f"{profit}*{name}")

        constraints: list[Constraint] = []

        for r in resources:
            r_name = r.get("name", "resource")
            available = r.get("available", 100)
            usage = r.get("usage", {})

            usage_terms = []
            for p in products:
                p_name = self.sanitize_name(p.get("name", ""))
                if p_name in usage:
                    usage_terms.append(f"{usage[p_name]}*{p_name}")

            if usage_terms:
                constraints.append(
                    Constraint(
                        name=self.sanitize_name(r_name),
                        expression=f"{' + '.join(usage_terms)} <= {available}",
                    )
                )

        return OptimizationProblem(
            name="production_planning",
            description=f"Plan production for {len(products)} products",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(profit_terms) if profit_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )

    def _generate_periodic(
        self, user_input: dict[str, Any], params: dict[str, Any]
    ) -> OptimizationProblem:
        """Multi-period production/resource allocation (e.g., reservoir operation)."""
        num_periods = int(user_input.get("periods", 6))
        capacity = float(user_input.get("reservoir_capacity", user_input.get("capacity", 100000)))
        initial = float(user_input.get("initial_volume", user_input.get("initial", 0)))

        inflows = user_input.get("inflows", [])
        demands = user_input.get("irrigation_demand", user_input.get("demand", []))

        variables: list[Variable] = []
        constraints: list[Constraint] = []

        # Release variables per period
        for t in range(1, num_periods + 1):
            variables.append(
                Variable(
                    name=f"release_{t}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=capacity,
                )
            )
            # Volume (state) variable
            variables.append(
                Variable(
                    name=f"vol_{t}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=capacity,
                )
            )

        # Balance constraints: vol_t = vol_{t-1} + inflow_t - release_t
        for t in range(1, num_periods + 1):
            inflow = 0.0
            for inf in inflows:
                if inf.get("period") == t:
                    inflow = float(inf.get("volume", 0))
                    break

            prev_vol = f"vol_{t - 1}" if t > 1 else str(initial)
            if t == 1:
                # vol_1 = initial + inflow_1 - release_1
                constraints.append(
                    Constraint(
                        name=f"balance_{t}",
                        expression=f"vol_{t} + release_{t} == {initial + inflow}",
                    )
                )
            else:
                constraints.append(
                    Constraint(
                        name=f"balance_{t}",
                        expression=f"vol_{t} - {prev_vol} + release_{t} == {inflow}",
                    )
                )

        # Meet irrigation demand
        for t in range(1, num_periods + 1):
            demand = 0.0
            for d in demands:
                if isinstance(d, dict) and d.get("period") == t:
                    demand = float(d.get("volume", 0))
                    break
            if demand > 0:
                constraints.append(
                    Constraint(
                        name=f"demand_{t}",
                        expression=f"release_{t} >= {demand}",
                    )
                )

        # Maximize total release (useful water)
        obj_terms = [f"release_{t}" for t in range(1, num_periods + 1)]

        return OptimizationProblem(
            name="periodic_production",
            description=f"Multi-period resource allocation over {num_periods} periods",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(obj_terms),
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )


class BudgetAllocationGenerator(BaseGenerator):
    """Generate budget allocation problems.

    Kept as a separate generator for backward compatibility with existing
    templates that use generator_type="budget_allocation".
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        total_budget = user_input.get("total_budget", 100000)
        departments = user_input.get("departments", [])
        objective_type = user_input.get("objective", "maximize_roi")

        variables: list[Variable] = []
        objective_terms: list[str] = []

        for dept in departments:
            name = self.sanitize_name(dept.get("name", f"dept_{len(variables)}"))
            min_alloc = dept.get("min_allocation", 0)
            max_alloc = dept.get("max_allocation", total_budget)
            roi = dept.get("expected_roi", 1.0)

            variables.append(
                Variable(
                    name=name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=min_alloc,
                    upper_bound=max_alloc,
                )
            )

            objective_terms.append(f"{roi}*{name}")

        all_vars = " + ".join(v.name for v in variables)
        constraints = [
            Constraint(
                name="total_budget",
                expression=f"{all_vars} <= {total_budget}",
            )
        ]

        sense = ObjectiveSense.MAXIMIZE if "max" in objective_type else ObjectiveSense.MINIMIZE
        objective_expr = " + ".join(objective_terms) if objective_terms else "0"

        return OptimizationProblem(
            name="budget_allocation",
            description=f"Allocate ${total_budget:,.0f} across {len(departments)} departments",
            variables=variables,
            objective=Objective(sense=sense, expression=objective_expr),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
