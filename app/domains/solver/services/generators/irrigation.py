"""Irrigation scheduling generator — 2D water allocation across fields and time slots.

Minimizes total water usage while meeting per-field crop requirements
and respecting per-slot pump capacity.
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


class IrrigationGenerator(BaseGenerator):
    """Generate irrigation scheduling problems (field × slot allocation)."""

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        fields = find_list_field(user_input, ["fields", "plots", "zones"])
        slots = find_list_field(user_input, ["slots", "time_slots", "periods"])
        if not fields or not slots:
            raise ValueError(
                f"Irrigation requires fields and slots lists. Got keys: {list(user_input.keys())}"
            )

        pump_capacity = float(
            user_input.get("pump_capacity_per_slot", user_input.get("pump_capacity", 0))
        )

        variables: list[Variable] = []
        all_terms: list[str] = []

        for field in fields:
            f_name = self.sanitize_name(field.get("name", ""))
            max_per_slot = float(field.get("max_per_slot", field.get("max_flow", 1000)))
            for slot in slots:
                s_name = self.sanitize_name(slot.get("name", ""))
                var_name = f"{f_name}_{s_name}"
                variables.append(
                    Variable(
                        name=var_name,
                        type=VariableType.CONTINUOUS,
                        lower_bound=0,
                        upper_bound=max_per_slot,
                    )
                )
                all_terms.append(var_name)

        constraints: list[Constraint] = []

        # Crop water requirement per field (sum across slots >= demand)
        for field in fields:
            f_name = self.sanitize_name(field.get("name", ""))
            demand = float(
                field.get("water_demand", field.get("demand", field.get("min_water", 0)))
            )
            if demand > 0:
                field_terms = [f"{f_name}_{self.sanitize_name(s.get('name', ''))}" for s in slots]
                constraints.append(
                    Constraint(
                        name=f"demand_{f_name}", expression=f"{' + '.join(field_terms)} >= {demand}"
                    )
                )

        # Pump capacity per slot (sum across fields <= capacity)
        if pump_capacity > 0:
            for slot in slots:
                s_name = self.sanitize_name(slot.get("name", ""))
                slot_terms = [f"{self.sanitize_name(f.get('name', ''))}_{s_name}" for f in fields]
                constraints.append(
                    Constraint(
                        name=f"pump_{s_name}",
                        expression=f"{' + '.join(slot_terms)} <= {pump_capacity}",
                    )
                )

        return OptimizationProblem(
            name="irrigation_scheduling",
            description=f"Schedule irrigation for {len(fields)} fields across {len(slots)} slots",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(all_terms) if all_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
