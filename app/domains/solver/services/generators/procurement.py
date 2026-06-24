"""Procurement generator — supplier selection and material purchasing.

Covers both single-material supplier selection and multi-material
procurement optimization with quality, capacity, and diversification
constraints.
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


class ProcurementGenerator(BaseGenerator):
    """Generate procurement/supplier selection problems.

    Single-material mode: suppliers compete to fill one demand.
    Multi-material mode: each (supplier, material) pair is a variable.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        suppliers = find_list_field(user_input, ["suppliers", "vendors", "sources"])
        if not suppliers:
            raise ValueError(
                f"Procurement requires a suppliers list. Got keys: {list(user_input.keys())}"
            )

        materials = user_input.get("materials", [])
        if materials:
            return self._generate_multi_material(user_input, suppliers, materials, params)
        return self._generate_single_material(user_input, suppliers, params)

    def _generate_single_material(
        self,
        user_input: dict[str, Any],
        suppliers: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> OptimizationProblem:
        """Single-material: choose order quantities per supplier."""
        total_demand = float(user_input.get("demand", user_input.get("total_demand", 0)))
        max_defect = user_input.get("max_average_defect_rate", user_input.get("max_defect_rate"))
        max_fraction = user_input.get(
            "max_single_supplier_fraction",
            user_input.get("diversification_limit"),
        )

        variables: list[Variable] = []
        cost_terms: list[str] = []
        demand_terms: list[str] = []

        for sup in suppliers:
            name = self.sanitize_name(sup.get("name", f"sup_{len(variables)}"))
            price = float(sup.get("unit_price", sup.get("price", sup.get("cost", 1))))
            capacity = sup.get("max_capacity", sup.get("capacity"))

            variables.append(
                Variable(
                    name=name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=float(capacity) if capacity is not None else None,
                )
            )
            cost_terms.append(f"{price}*{name}")
            demand_terms.append(name)

        constraints: list[Constraint] = []

        # Demand satisfaction
        if total_demand > 0:
            constraints.append(
                Constraint(
                    name="demand_satisfaction",
                    expression=f"{' + '.join(demand_terms)} >= {total_demand}",
                )
            )

        # Quality constraint: weighted average defect rate
        if max_defect is not None and max_defect > 0:
            # SUM(defect_rate_i * qty_i) <= max_defect * SUM(qty_i)
            # => SUM((defect_rate_i - max_defect) * qty_i) <= 0
            quality_terms = []
            for sup, var in zip(suppliers, variables, strict=True):
                defect = float(sup.get("defect_rate", sup.get("rejection_rate", 0)))
                coef = defect - max_defect
                if abs(coef) > 1e-10:
                    quality_terms.append(f"{coef}*{var.name}")
            if quality_terms:
                constraints.append(
                    Constraint(
                        name="quality_limit",
                        expression=f"{' + '.join(quality_terms)} <= 0",
                    )
                )

        # Diversification: no single supplier exceeds fraction of demand
        if max_fraction is not None and total_demand > 0:
            max_qty = max_fraction * total_demand
            for var in variables:
                constraints.append(
                    Constraint(
                        name=f"diversify_{var.name}",
                        expression=f"{var.name} <= {max_qty}",
                    )
                )

        return OptimizationProblem(
            name="supplier_selection",
            description=f"Select from {len(suppliers)} suppliers to fill demand of {total_demand}",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )

    def _generate_multi_material(
        self,
        user_input: dict[str, Any],
        suppliers: list[dict[str, Any]],
        materials: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> OptimizationProblem:
        """Multi-material: one variable per (supplier, material) pair."""
        variables: list[Variable] = []
        cost_terms: list[str] = []

        # Build variable for each (supplier, material) pair
        for sup in suppliers:
            sup_name = self.sanitize_name(sup.get("name", f"sup_{len(variables)}"))
            pricing = sup.get("pricing", {})
            max_total = sup.get("max_total_supply", sup.get("capacity"))

            for mat in materials:
                mat_name = self.sanitize_name(mat.get("name", ""))
                var_name = f"{sup_name}_{mat_name}"
                price = float(pricing.get(mat.get("name", ""), pricing.get(mat_name, 1)))

                # Per-pair capacity from supplier's per-material limits
                per_mat_cap = sup.get("per_material_capacity", {}).get(mat.get("name"))

                variables.append(
                    Variable(
                        name=var_name,
                        type=VariableType.CONTINUOUS,
                        lower_bound=0,
                        upper_bound=float(per_mat_cap) if per_mat_cap is not None else None,
                    )
                )
                cost_terms.append(f"{price}*{var_name}")

        constraints: list[Constraint] = []

        # Demand satisfaction per material
        for mat in materials:
            mat_name = self.sanitize_name(mat.get("name", ""))
            demand = float(mat.get("demand", 0))
            mat_terms = [v.name for v in variables if v.name.endswith(f"_{mat_name}")]
            if mat_terms and demand > 0:
                constraints.append(
                    Constraint(
                        name=f"demand_{mat_name}",
                        expression=f"{' + '.join(mat_terms)} >= {demand}",
                    )
                )

        # Total capacity per supplier (across all materials)
        for sup in suppliers:
            sup_name = self.sanitize_name(sup.get("name", ""))
            max_total = sup.get("max_total_supply", sup.get("capacity"))
            if max_total is not None:
                sup_terms = [v.name for v in variables if v.name.startswith(f"{sup_name}_")]
                if sup_terms:
                    constraints.append(
                        Constraint(
                            name=f"cap_{sup_name}",
                            expression=f"{' + '.join(sup_terms)} <= {max_total}",
                        )
                    )

        return OptimizationProblem(
            name="material_procurement",
            description=(f"Procure {len(materials)} materials from {len(suppliers)} suppliers"),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
