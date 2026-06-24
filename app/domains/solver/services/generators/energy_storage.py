"""Energy storage dispatch generator — battery charge/discharge scheduling.

Optimizes charge and discharge decisions across time periods to maximize
arbitrage profit, respecting battery physics (capacity, efficiency, rate limits).
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


class EnergyStorageGenerator(BaseGenerator):
    """Generate battery dispatch optimization problems.

    For each period: decide how much to charge and discharge.
    State of charge (SoC) tracks energy stored across periods.
    Objective: maximize profit from price arbitrage.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        periods = find_list_field(user_input, ["periods", "time_slots", "hours"])
        if not periods:
            raise ValueError(
                f"Energy storage requires a periods list. Got keys: {list(user_input.keys())}"
            )

        battery = user_input.get("battery", {})
        capacity = float(battery.get("capacity_kWh", battery.get("capacity", 500)))
        max_charge = float(battery.get("max_charge_rate_kW", battery.get("max_charge", 100)))
        max_discharge = float(
            battery.get("max_discharge_rate_kW", battery.get("max_discharge", 100))
        )
        efficiency = float(battery.get("round_trip_efficiency", battery.get("efficiency", 0.9)))
        initial_soc_frac = float(battery.get("initial_soc", 0.5))
        initial_soc = initial_soc_frac * capacity if initial_soc_frac <= 1.0 else initial_soc_frac

        # Charge efficiency split: sqrt(round_trip) for each direction
        charge_eff = efficiency**0.5
        discharge_eff = efficiency**0.5

        variables: list[Variable] = []
        profit_terms: list[str] = []

        # Create charge, discharge, and SoC variables for each period
        for i, period in enumerate(periods):
            name = self.sanitize_name(period.get("name", f"t_{i + 1}"))
            price = float(period.get("price_per_kWh", period.get("price", period.get("cost", 0.1))))

            charge_var = f"charge_{name}"
            discharge_var = f"discharge_{name}"
            soc_var = f"soc_{name}"

            mode_var = f"charging_{name}"  # 1=charging, 0=discharging

            variables.append(
                Variable(
                    name=charge_var,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=max_charge,
                )
            )
            variables.append(
                Variable(
                    name=discharge_var,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=max_discharge,
                )
            )
            variables.append(
                Variable(
                    name=soc_var, type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=capacity
                )
            )
            variables.append(Variable(name=mode_var, type=VariableType.BINARY))

            profit_terms.append(f"{price}*{discharge_var}")
            profit_terms.append(f"-{price}*{charge_var}")

        constraints: list[Constraint] = []

        # SoC balance: soc_t = soc_{t-1} + charge_eff * charge_t - discharge_t / discharge_eff
        # Rearranged: soc_t - charge_eff * charge_t + (1/discharge_eff) * discharge_t = soc_{t-1}
        for i, period in enumerate(periods):
            name = self.sanitize_name(period.get("name", f"t_{i + 1}"))
            soc_var = f"soc_{name}"
            charge_var = f"charge_{name}"
            discharge_var = f"discharge_{name}"

            prev_soc = (
                initial_soc
                if i == 0
                else f"soc_{self.sanitize_name(periods[i - 1].get('name', f't_{i}'))}"
            )
            inv_discharge_eff = round(1.0 / discharge_eff, 6)

            if i == 0:
                # soc_0 - charge_eff * charge_0 + inv_eff * discharge_0 = initial_soc
                constraints.append(
                    Constraint(
                        name=f"soc_balance_{name}",
                        expression=(
                            f"{soc_var} - {charge_eff}*{charge_var} "
                            f"+ {inv_discharge_eff}*{discharge_var} == {initial_soc}"
                        ),
                    )
                )
            else:
                # soc_t - soc_{t-1} - charge_eff * charge_t + inv_eff * discharge_t = 0
                constraints.append(
                    Constraint(
                        name=f"soc_balance_{name}",
                        expression=(
                            f"{soc_var} - {prev_soc} - {charge_eff}*{charge_var} "
                            f"+ {inv_discharge_eff}*{discharge_var} == 0"
                        ),
                    )
                )

        # Charge/discharge exclusion: cannot charge and discharge simultaneously
        for i, period in enumerate(periods):
            name = self.sanitize_name(period.get("name", f"t_{i + 1}"))
            constraints.append(
                Constraint(
                    name=f"charge_only_{name}",
                    expression=f"charge_{name} - {max_charge}*charging_{name} <= 0",
                )
            )
            constraints.append(
                Constraint(
                    name=f"discharge_only_{name}",
                    expression=f"discharge_{name} + {max_discharge}*charging_{name} <= {max_discharge}",
                )
            )

        return OptimizationProblem(
            name="energy_storage_dispatch",
            description=f"Optimize battery dispatch across {len(periods)} periods (capacity={capacity} kWh)",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(profit_terms) if profit_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
