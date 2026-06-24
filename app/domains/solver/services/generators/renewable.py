"""Renewable curtailment generator — grid capacity allocation.

Allocates generation from renewable sources to the grid per period,
minimizing curtailment (wasted energy) while respecting grid transmission limits.
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


class RenewableCurtailmentGenerator(BaseGenerator):
    """Generate renewable curtailment minimization problems.

    For each (generator, period): alloc + curtail = forecast.
    Grid limit: sum(alloc) <= grid_capacity per period.
    Objective: minimize total curtailment.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        generators = find_list_field(user_input, ["generators", "sources", "plants", "turbines"])
        periods = find_list_field(user_input, ["periods", "hours", "time_slots"])
        if not generators or not periods:
            raise ValueError(
                f"Renewable curtailment requires generators and periods. "
                f"Got keys: {list(user_input.keys())}"
            )

        grid_capacity = float(
            user_input.get("grid_capacity", user_input.get("transmission_limit", 0))
        )

        # Pre-compute forecasts: (g_name, p_name) → float
        forecast_map: dict[tuple[str, str], float] = {}
        for gen in generators:
            g_name = self.sanitize_name(gen.get("name", ""))
            forecasts = gen.get("forecast", gen.get("output", {}))
            for i, period in enumerate(periods):
                p_name = self.sanitize_name(period.get("name", ""))
                forecast = 0.0
                if isinstance(forecasts, dict):
                    forecast = float(
                        forecasts.get(period.get("name", ""), forecasts.get(p_name, 0))
                    )
                elif isinstance(forecasts, list):
                    forecast = float(forecasts[i]) if i < len(forecasts) else 0.0
                forecast_map[(g_name, p_name)] = forecast

        variables: list[Variable] = []
        curtail_terms: list[str] = []

        for gen in generators:
            g_name = self.sanitize_name(gen.get("name", ""))
            for period in periods:
                p_name = self.sanitize_name(period.get("name", ""))
                forecast = forecast_map[(g_name, p_name)]

                alloc_var = f"alloc_{g_name}_{p_name}"
                curtail_var = f"curtail_{g_name}_{p_name}"

                variables.append(
                    Variable(
                        name=alloc_var,
                        type=VariableType.CONTINUOUS,
                        lower_bound=0,
                        upper_bound=forecast,
                    )
                )
                variables.append(
                    Variable(
                        name=curtail_var,
                        type=VariableType.CONTINUOUS,
                        lower_bound=0,
                        upper_bound=forecast,
                    )
                )
                curtail_terms.append(curtail_var)

        constraints: list[Constraint] = []

        for gen in generators:
            g_name = self.sanitize_name(gen.get("name", ""))
            for period in periods:
                p_name = self.sanitize_name(period.get("name", ""))
                forecast = forecast_map[(g_name, p_name)]
                constraints.append(
                    Constraint(
                        name=f"balance_{g_name}_{p_name}",
                        expression=f"alloc_{g_name}_{p_name} + curtail_{g_name}_{p_name} == {forecast}",
                    )
                )

        # Grid capacity per period
        if grid_capacity > 0:
            for period in periods:
                p_name = self.sanitize_name(period.get("name", ""))
                alloc_terms = [
                    f"alloc_{self.sanitize_name(g.get('name', ''))}_{p_name}" for g in generators
                ]
                constraints.append(
                    Constraint(
                        name=f"grid_{p_name}",
                        expression=f"{' + '.join(alloc_terms)} <= {grid_capacity}",
                    )
                )

        return OptimizationProblem(
            name="renewable_curtailment",
            description=f"Minimize curtailment for {len(generators)} generators across {len(periods)} periods",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(curtail_terms) if curtail_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
