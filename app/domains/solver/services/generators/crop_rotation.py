"""Crop rotation generator — multi-season field-crop assignment.

Assigns crops to fields across seasons maximizing profit while enforcing
rotation rules (no repeated crop family in consecutive seasons), water
limits, and one-crop-per-field-per-season exclusivity.
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


class CropRotationGenerator(BaseGenerator):
    """Generate crop rotation planning problems."""

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        crops = find_list_field(user_input, ["crops", "crop_options", "plants"])
        fields = find_list_field(user_input, ["fields", "plots", "parcels"])
        seasons = find_list_field(user_input, ["seasons", "periods", "years"])
        if not crops or not fields:
            raise ValueError(
                f"Crop rotation requires crops and fields lists. Got keys: {list(user_input.keys())}"
            )
        if not seasons:
            num_seasons = int(user_input.get("num_seasons", 2))
            seasons = [{"name": f"S{i + 1}"} for i in range(num_seasons)]

        water_per_season = float(
            user_input.get("water_per_season", user_input.get("water_limit", 0))
        )
        no_repeat_crops = user_input.get("no_repeat", [c.get("name", "") for c in crops])

        variables: list[Variable] = []
        profit_terms: list[str] = []

        # Binary variable per (crop, field, season)
        for crop in crops:
            c_name = self.sanitize_name(crop.get("name", ""))
            profit = float(crop.get("profit", crop.get("revenue", crop.get("yield_value", 0))))
            for field in fields:
                f_name = self.sanitize_name(field.get("name", ""))
                for season in seasons:
                    s_name = self.sanitize_name(season.get("name", ""))
                    var_name = f"{c_name}_{f_name}_{s_name}"
                    variables.append(Variable(name=var_name, type=VariableType.BINARY))
                    if profit:
                        profit_terms.append(f"{profit}*{var_name}")

        constraints: list[Constraint] = []

        # One crop per field per season
        for field in fields:
            f_name = self.sanitize_name(field.get("name", ""))
            for season in seasons:
                s_name = self.sanitize_name(season.get("name", ""))
                terms = [
                    f"{self.sanitize_name(c.get('name', ''))}_{f_name}_{s_name}" for c in crops
                ]
                constraints.append(
                    Constraint(
                        name=f"one_crop_{f_name}_{s_name}",
                        expression=f"{' + '.join(terms)} <= 1",
                    )
                )

        # Rotation: no repeat of same crop in consecutive seasons on same field
        if isinstance(no_repeat_crops, list):
            crop_names_to_check = [
                c if isinstance(c, str) else c.get("name", "") for c in no_repeat_crops
            ]
        else:
            crop_names_to_check = [c.get("name", "") for c in crops]

        for crop_name in crop_names_to_check:
            c_name = self.sanitize_name(crop_name)
            for field in fields:
                f_name = self.sanitize_name(field.get("name", ""))
                for i in range(len(seasons) - 1):
                    s1 = self.sanitize_name(seasons[i].get("name", ""))
                    s2 = self.sanitize_name(seasons[i + 1].get("name", ""))
                    constraints.append(
                        Constraint(
                            name=f"norepeat_{c_name}_{f_name}_{s1}_{s2}",
                            expression=f"{c_name}_{f_name}_{s1} + {c_name}_{f_name}_{s2} <= 1",
                        )
                    )

        # Water limit per season
        if water_per_season > 0:
            for season in seasons:
                s_name = self.sanitize_name(season.get("name", ""))
                water_terms = []
                for crop in crops:
                    c_name = self.sanitize_name(crop.get("name", ""))
                    water = float(crop.get("water_need", crop.get("water", 0)))
                    if water > 0:
                        for field in fields:
                            f_name = self.sanitize_name(field.get("name", ""))
                            water_terms.append(f"{water}*{c_name}_{f_name}_{s_name}")
                if water_terms:
                    constraints.append(
                        Constraint(
                            name=f"water_{s_name}",
                            expression=f"{' + '.join(water_terms)} <= {water_per_season}",
                        )
                    )

        return OptimizationProblem(
            name="crop_rotation",
            description=f"Plan {len(crops)} crops across {len(fields)} fields and {len(seasons)} seasons",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(profit_terms) if profit_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
