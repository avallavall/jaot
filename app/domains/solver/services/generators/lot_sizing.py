"""Lot sizing generator — single/multi-item lot sizing with setup costs."""

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


class LotSizingGenerator(BaseGenerator):
    """Generate single-item lot sizing problems.

    Decide how much to produce each period to meet demand, with setup costs
    when production occurs and holding costs for inventory.

    Variables per period:
    - x_t: production quantity (integer)
    - y_t: setup indicator (binary, 1 if production occurs)
    - s_t: inventory at end of period (continuous)

    Balance: s_{t-1} + x_t - demand_t = s_t
    Setup link: x_t <= capacity * y_t
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        periods = user_input.get("periods", 1)
        demand = user_input.get("demand", [0] * periods)
        production_cost = user_input.get("production_cost", 1)
        setup_cost = user_input.get("setup_cost", 0)
        holding_cost = user_input.get("holding_cost", 0)
        capacity = user_input.get("capacity", sum(demand))
        initial_inventory = user_input.get("initial_inventory", 0)

        variables: list[Variable] = []
        cost_terms: list[str] = []
        constraints: list[Constraint] = []

        for t in range(periods):
            # Production quantity
            x_name = f"prod_{t}"
            variables.append(
                Variable(
                    name=x_name,
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=capacity,
                )
            )
            cost_terms.append(f"{production_cost}*{x_name}")

            # Setup indicator
            y_name = f"setup_{t}"
            variables.append(Variable(name=y_name, type=VariableType.BINARY))
            cost_terms.append(f"{setup_cost}*{y_name}")

            # Inventory at end of period
            s_name = f"inv_{t}"
            variables.append(
                Variable(
                    name=s_name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                )
            )
            cost_terms.append(f"{holding_cost}*{s_name}")

            # Setup link: x_t <= capacity * y_t
            constraints.append(
                Constraint(
                    name=f"setup_link_{t}",
                    expression=f"{x_name} - {capacity}*{y_name} <= 0",
                )
            )

            # Inventory balance: s_{t-1} + x_t - demand_t = s_t
            d_t = demand[t] if t < len(demand) else 0
            if t == 0:
                # s_{-1} = initial_inventory
                constraints.append(
                    Constraint(
                        name=f"balance_{t}",
                        expression=f"{x_name} - {s_name} == {d_t - initial_inventory}",
                    )
                )
            else:
                prev_s = f"inv_{t - 1}"
                constraints.append(
                    Constraint(
                        name=f"balance_{t}",
                        expression=f"{prev_s} + {x_name} - {s_name} == {d_t}",
                    )
                )

        return OptimizationProblem(
            name="lot_sizing",
            description=f"Lot sizing over {periods} periods with setup and holding costs",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
