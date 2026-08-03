"""Blending generator — generalized mixing/blending problems.

Supports domain-specific input formats (chemical feedstocks, recipe ingredients,
ore sources) by auto-detecting lists of materials and quality specifications.
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


class BlendingGenerator(BaseGenerator):
    """Generate blending/mixing problems.

    Minimizes cost while meeting component percentage targets.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        raw_materials = find_list_field(
            user_input,
            [
                "raw_materials",
                "materials",
                "feedstocks",
                "ingredients",
                "sources",
            ],
        )
        target_nutrients = find_list_field(
            user_input,
            [
                "target_nutrients",
                "specifications",
                "quality_specs",
                "targets",
            ],
        )
        # An explicit mix_quantity_min/max is a bound. A batch size or target
        # tonnage is the quantity to PRODUCE: treating it as only a ceiling let
        # "produce nothing" satisfy every ratio spec, and three shipped cards
        # answered an optimal cost of 0 for blends nobody would make.
        production_target = user_input.get("batch_size", user_input.get("target_tonnage", -1))
        mix_quantity_min = user_input.get("mix_quantity_min", 0)
        mix_quantity_max = user_input.get("mix_quantity_max", production_target)
        if not mix_quantity_min and production_target > 0:
            mix_quantity_min = production_target

        variables: list[Variable] = []
        cost_terms: list[str] = []
        total_qty_terms: list[str] = []

        for rm in raw_materials:
            rm_id = self.sanitize_name(rm.get("id", rm.get("name", f"rm_{len(variables)}")))
            # Support multiple price field names. Only price_per_ton normalizes
            # (kg-denominated cards); the others already match their quantity
            # unit. cost_per_liter / cost_per_tonne went unread before, so
            # buying was free and the optimum was always a cost of 0.
            price = rm.get(
                "price_per_ton",
                rm.get(
                    "cost_per_kg",
                    rm.get(
                        "cost_per_liter",
                        rm.get("cost_per_tonne", rm.get("unit_cost", rm.get("price", 0))),
                    ),
                ),
            )
            if rm.get("price_per_ton"):
                price = price / 1000.0  # normalize to per-kg

            qty_min = max(0, rm.get("quantity_min", rm.get("min_qty", 0)))
            qty_max = rm.get("quantity_max", rm.get("max_qty", -1))
            stock_max = rm.get("stock_max", rm.get("available", -1))

            upper = None
            if qty_max >= 0 and stock_max >= 0:
                upper = min(qty_max, stock_max)
            elif qty_max >= 0:
                upper = qty_max
            elif stock_max >= 0:
                upper = stock_max

            variables.append(
                Variable(
                    name=rm_id,
                    type=VariableType.CONTINUOUS,
                    lower_bound=qty_min,
                    upper_bound=upper,
                )
            )

            cost_terms.append(f"{price}*{rm_id}")
            total_qty_terms.append(rm_id)

        if not variables:
            raise ValueError(
                "Blending generator requires raw materials/ingredients. "
                f"Got keys: {list(user_input.keys())}"
            )

        constraints: list[Constraint] = []

        total_qty_expr = " + ".join(total_qty_terms)

        if mix_quantity_min > 0:
            constraints.append(
                Constraint(
                    name="mix_quantity_min",
                    expression=f"{total_qty_expr} >= {mix_quantity_min}",
                )
            )

        if mix_quantity_max > 0:
            constraints.append(
                Constraint(
                    name="mix_quantity_max",
                    expression=f"{total_qty_expr} <= {mix_quantity_max}",
                )
            )

        # Nutrient/component constraints (percentage or absolute mode)
        absolute_mode = params.get("mode") == "absolute"

        for target in target_nutrients:
            nutrient_id = target.get(
                "id",
                target.get(
                    "name",
                    target.get(
                        "property",
                        target.get(
                            "component", target.get("nutrient", target.get("parameter", ""))
                        ),
                    ),
                ),
            )
            min_val = target.get(
                "min", target.get("min_pct", target.get("min_per_kg", target.get("min_value", 0)))
            )
            max_val = target.get(
                "max", target.get("max_pct", target.get("max_per_kg", target.get("max_value", 0)))
            )

            if absolute_mode:
                self._add_absolute_constraints(
                    constraints,
                    raw_materials,
                    nutrient_id,
                    min_val,
                    max_val,
                )
            else:
                self._add_percentage_constraints(
                    constraints,
                    raw_materials,
                    nutrient_id,
                    min_val,
                    max_val,
                )

        problem_name = params.get("problem_name", "blending")
        description = params.get(
            "description",
            f"Optimize blend with {len(raw_materials)} materials"
            f" and {len(target_nutrients)} component targets",
        )

        return OptimizationProblem(
            name=problem_name,
            description=description,
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def _get_nutrient_value(self, rm: dict[str, Any], nutrient_id: str) -> float:
        """Extract nutrient content from a material, trying multiple formats."""
        # Structured: list of {id, percentage} entries, or a flat {name: value}
        # dict (the recipe cards ship the dict form).
        structured = rm.get("nutrient_percentages", rm.get("nutrients", []))
        if isinstance(structured, dict):
            val = structured.get(nutrient_id, 0)
            if val:
                return float(val)
        else:
            for np_item in structured:
                if np_item.get("id") == nutrient_id:
                    return float(
                        np_item.get("percentage", np_item.get("amount", np_item.get("value", 0)))
                    )
        # Flat composition dict
        if "composition" in rm:
            val = rm["composition"].get(nutrient_id, 0)
            if val:
                return float(val)
        # Direct field: e.g., "protein" or "protein_content"
        val = rm.get(f"{nutrient_id}_content", rm.get(nutrient_id, 0))
        return float(val)

    def _add_percentage_constraints(
        self,
        constraints: list[Constraint],
        raw_materials: list[dict[str, Any]],
        nutrient_id: str,
        min_pct: float,
        max_pct: float,
    ) -> None:
        """Add percentage-based nutrient constraints (standard blending mode)."""
        if min_pct > 0:
            terms = []
            for rm in raw_materials:
                rm_id = self.sanitize_name(rm.get("id", rm.get("name", "")))
                pct = self._get_nutrient_value(rm, nutrient_id)
                coef = (pct / 100.0) - (min_pct / 100.0)
                if abs(coef) > 1e-10:
                    terms.append(f"{coef}*{rm_id}")
            if terms:
                constraints.append(
                    Constraint(name=f"min_{nutrient_id}", expression=f"{' + '.join(terms)} >= 0")
                )

        if max_pct > 0:
            terms = []
            for rm in raw_materials:
                rm_id = self.sanitize_name(rm.get("id", rm.get("name", "")))
                pct = self._get_nutrient_value(rm, nutrient_id)
                coef = (max_pct / 100.0) - (pct / 100.0)
                if abs(coef) > 1e-10:
                    terms.append(f"{coef}*{rm_id}")
            if terms:
                constraints.append(
                    Constraint(name=f"max_{nutrient_id}", expression=f"{' + '.join(terms)} >= 0")
                )

    def _add_absolute_constraints(
        self,
        constraints: list[Constraint],
        raw_materials: list[dict[str, Any]],
        nutrient_id: str,
        min_amount: float,
        max_amount: float,
    ) -> None:
        """Add absolute-amount nutrient constraints (diet/nutrition mode).

        Uses SUM(content_i * x_i) >= min_amount instead of percentage linearization.
        """
        if min_amount > 0:
            terms = []
            for rm in raw_materials:
                rm_id = self.sanitize_name(rm.get("id", rm.get("name", "")))
                content = self._get_nutrient_value(rm, nutrient_id)
                if abs(content) > 1e-10:
                    terms.append(f"{content}*{rm_id}")
            if terms:
                constraints.append(
                    Constraint(
                        name=f"min_{nutrient_id}",
                        expression=f"{' + '.join(terms)} >= {min_amount}",
                    )
                )

        if max_amount > 0:
            terms = []
            for rm in raw_materials:
                rm_id = self.sanitize_name(rm.get("id", rm.get("name", "")))
                content = self._get_nutrient_value(rm, nutrient_id)
                if abs(content) > 1e-10:
                    terms.append(f"{content}*{rm_id}")
            if terms:
                constraints.append(
                    Constraint(
                        name=f"max_{nutrient_id}",
                        expression=f"{' + '.join(terms)} <= {max_amount}",
                    )
                )
