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

        self.reject_name_collisions(
            [self.sanitize_name(f.get("name", "")) for f in fields],
            [f.get("name") for f in fields],
            "Fields",
        )
        self.reject_name_collisions(
            [self.sanitize_name(s.get("name", "")) for s in slots],
            [s.get("name") for s in slots],
            "Slots",
        )

        # What separates one slot from another. Water applied at midday largely
        # evaporates before it reaches the root zone, and pumping costs what the
        # tariff band costs at that hour. Without either figure the objective was
        # "minimize total water" against demand rows that already pin the total,
        # so every schedule tied on the same number and the card reported an
        # arbitrary one as optimal — for a card whose whole answer IS the
        # schedule.
        losses: dict[str, float] = {}
        tariffs: dict[str, float] = {}
        for slot in slots:
            s_name = self.sanitize_name(slot.get("name", ""))
            loss = float(slot.get("evaporation_loss", slot.get("loss", 0.0)))
            if not 0.0 <= loss < 1.0:
                raise ValueError(
                    f"Slot '{slot.get('name', s_name)}' states an evaporation_loss of {loss}. "
                    "It is the fraction of applied water lost, so it belongs in [0, 1)."
                )
            losses[s_name] = loss
            tariff = slot.get("energy_cost_per_unit", slot.get("pumping_cost_per_unit"))
            if tariff is not None:
                tariffs[s_name] = float(tariff)

        # All slots price their pumping, or none does. A partial table would
        # cost the unpriced slots at zero and empty the whole schedule into them.
        if tariffs and len(tariffs) != len(slots):
            missing = [
                s.get("name") for s in slots if self.sanitize_name(s.get("name", "")) not in tariffs
            ]
            raise ValueError(
                f"These slots state no energy_cost_per_unit: {missing}. Price every slot "
                "or none: an unpriced slot costs nothing and takes the whole schedule."
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
                # What the crop receives, not what the pump moves: a slot that
                # loses 35% has to run harder to deliver the same litre.
                field_terms = []
                for s in slots:
                    s_name = self.sanitize_name(s.get("name", ""))
                    delivered = round(1.0 - losses[s_name], 6)
                    field_terms.append(f"{delivered}*{f_name}_{s_name}")
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

        # Minimize what the pumping costs when the slots are priced; otherwise
        # fall back to minimizing the water moved.
        if tariffs:
            objective_terms = []
            for field in fields:
                f_name = self.sanitize_name(field.get("name", ""))
                for s in slots:
                    s_name = self.sanitize_name(s.get("name", ""))
                    objective_terms.append(f"{tariffs[s_name]}*{f_name}_{s_name}")
        else:
            objective_terms = all_terms

        return OptimizationProblem(
            name="irrigation_scheduling",
            description=f"Schedule irrigation for {len(fields)} fields across {len(slots)} slots",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(objective_terms) if objective_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
