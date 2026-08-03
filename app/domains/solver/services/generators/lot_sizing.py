"""Lot sizing generator — single/multi-item lot sizing with setup costs."""

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
        # Multi-item inputs (a products/skus list, each with its own demand
        # series) used to fall through to the single-item reader, which found
        # no top-level demand and served a one-period model of nothing — two
        # shipped cards answered an optimal cost of 0.
        items = find_list_field(user_input, ["products", "skus", "items"], fallback=False)
        if items and any(isinstance(item.get("demand"), list) for item in items):
            return self._generate_multi_item(user_input, items)

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

        # Per-period big-M: producing more than the demand still ahead is never
        # useful, so the setup link tightens from `capacity` (default: TOTAL
        # demand) to min(capacity, remaining demand). Same rows, same optimum —
        # measured on 24 periods with the default capacity: root LP bound
        # 3675 → 5968 (gap 75.6% → 60.4%) at identical MIP optimum.
        remaining = [sum(demand[t:]) for t in range(periods)]

        for t in range(periods):
            m_t = min(capacity, remaining[t]) if remaining[t] > 0 else capacity

            # Production quantity
            x_name = f"prod_{t}"
            variables.append(
                Variable(
                    name=x_name,
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=m_t,
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

            # Setup link: x_t <= M_t * y_t
            constraints.append(
                Constraint(
                    name=f"setup_link_{t}",
                    expression=f"{x_name} - {m_t}*{y_name} <= 0",
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

    def _generate_multi_item(
        self, user_input: dict[str, Any], items: list[dict[str, Any]]
    ) -> OptimizationProblem:
        """Independent lot sizing per item, optionally coupled by reactors.

        Per item and period: production (in integer batches when the item
        declares a ``batch_size``), a setup indicator and inventory, with the
        same declining big-M as the single-item model. ``num_reactors`` couples
        the items: at most that many setups in any one period.
        """
        num_periods = int(user_input.get("num_periods", user_input.get("periods", 0)))
        if num_periods <= 0:
            num_periods = max(len(item.get("demand", [])) for item in items)
        num_reactors = int(user_input.get("num_reactors", user_input.get("num_lines", 0)))

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        cost_terms: list[str] = []
        setups_by_period: dict[int, list[str]] = {t: [] for t in range(num_periods)}

        for i, item in enumerate(items):
            name = self.sanitize_name(item.get("name", f"item_{i}"))
            demand = [
                float(item.get("demand", [])[t]) if t < len(item.get("demand", [])) else 0.0
                for t in range(num_periods)
            ]
            production_cost = float(item.get("production_cost", item.get("unit_cost", 0)))
            setup_cost = float(item.get("setup_cost", item.get("ordering_cost", 0)))
            holding_cost = float(item.get("holding_cost", 0))
            batch_size = float(item.get("batch_size", 0))
            initial_inventory = float(item.get("initial_inventory", 0))
            remaining = [sum(demand[t:]) for t in range(num_periods)]

            for t in range(num_periods):
                m_t = remaining[t] if remaining[t] > 0 else sum(demand)
                x_name = f"prod_{name}_{t}"
                y_name = f"setup_{name}_{t}"
                s_name = f"inv_{name}_{t}"

                if batch_size > 0:
                    # Production comes in whole batches; costs are per batch.
                    b_name = f"batches_{name}_{t}"
                    max_batches = int(m_t // batch_size) + 1
                    variables.append(
                        Variable(
                            name=b_name,
                            type=VariableType.INTEGER,
                            lower_bound=0,
                            upper_bound=max_batches,
                        )
                    )
                    variables.append(
                        Variable(
                            name=x_name,
                            type=VariableType.CONTINUOUS,
                            lower_bound=0,
                            upper_bound=max_batches * batch_size,
                        )
                    )
                    constraints.append(
                        Constraint(
                            name=f"batches_{name}_{t}_link",
                            expression=f"{x_name} - {batch_size}*{b_name} == 0",
                        )
                    )
                    constraints.append(
                        Constraint(
                            name=f"setup_link_{name}_{t}",
                            expression=f"{b_name} - {max_batches}*{y_name} <= 0",
                        )
                    )
                    cost_terms.append(f"{production_cost}*{b_name}")
                else:
                    variables.append(
                        Variable(
                            name=x_name,
                            type=VariableType.INTEGER,
                            lower_bound=0,
                            upper_bound=m_t,
                        )
                    )
                    constraints.append(
                        Constraint(
                            name=f"setup_link_{name}_{t}",
                            expression=f"{x_name} - {m_t}*{y_name} <= 0",
                        )
                    )
                    cost_terms.append(f"{production_cost}*{x_name}")

                variables.append(Variable(name=y_name, type=VariableType.BINARY))
                cost_terms.append(f"{setup_cost}*{y_name}")
                setups_by_period[t].append(y_name)

                variables.append(Variable(name=s_name, type=VariableType.CONTINUOUS, lower_bound=0))
                cost_terms.append(f"{holding_cost}*{s_name}")

                if t == 0:
                    constraints.append(
                        Constraint(
                            name=f"balance_{name}_{t}",
                            expression=(f"{x_name} - {s_name} == {demand[t] - initial_inventory}"),
                        )
                    )
                else:
                    constraints.append(
                        Constraint(
                            name=f"balance_{name}_{t}",
                            expression=f"inv_{name}_{t - 1} + {x_name} - {s_name} == {demand[t]}",
                        )
                    )

        # Shared production lines: at most num_reactors setups per period.
        if 0 < num_reactors < len(items):
            for t, setups in setups_by_period.items():
                if len(setups) > num_reactors:
                    constraints.append(
                        Constraint(
                            name=f"reactors_{t}",
                            expression=f"{' + '.join(setups)} <= {num_reactors}",
                        )
                    )

        return OptimizationProblem(
            name="multi_item_lot_sizing",
            description=(
                f"Lot sizing for {len(items)} items over {num_periods} periods"
                + (f" on {num_reactors} shared lines" if num_reactors else "")
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
