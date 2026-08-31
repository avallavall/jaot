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

    #: A supplier row that names the one material it offers uses the quoted
    #: layout; a row carrying a ``pricing`` map prices every material.
    _OFFERED_KEYS = ("material", "ingredient", "product", "item")
    _PRICE_KEYS = ("price_per_unit", "price_per_kg", "price_per_tonne", "unit_price", "price")
    _DEMAND_KEYS = ("demand", "required_qty", "required_quantity", "quantity")

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        suppliers = find_list_field(user_input, ["suppliers", "vendors", "sources"])
        if not suppliers:
            raise ValueError(
                f"Procurement requires a suppliers list. Got keys: {list(user_input.keys())}"
            )

        materials = find_list_field(
            user_input, ["materials", "ingredients", "products"], fallback=False
        )
        if materials and any(self._offered_material(s) for s in suppliers):
            return self._generate_quoted_rows(user_input, suppliers, materials, params)
        if materials:
            return self._generate_multi_material(user_input, suppliers, materials, params)
        return self._generate_single_material(user_input, suppliers, params)

    def _offered_material(self, supplier: dict[str, Any]) -> str | None:
        """The single material this supplier row quotes for, if it names one."""
        for key in self._OFFERED_KEYS:
            value = supplier.get(key)
            if isinstance(value, str) and value:
                return value
        return None

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

    def _generate_quoted_rows(
        self,
        user_input: dict[str, Any],
        suppliers: list[dict[str, Any]],
        materials: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> OptimizationProblem:
        """One row per supplier quote: this supplier, this material, this price.

        Buy a quantity from each quote, cover every material's requirement, and
        respect each quote's capacity. A quote with a ``delivery_cost`` or a
        ``min_order`` also gets a binary "use this supplier" so the fixed charge
        is paid once and a used supplier is ordered from properly. These cards
        used to reach the knapsack generator, which read the material names and
        nothing else: three variables, one constraint, and every price,
        capacity and requirement thrown away.
        """
        # `required` is keyed by the sanitized material name, so two materials
        # that sanitize alike overwrite each other and one purchase requirement
        # row vanishes with no error at all.
        self.reject_name_collisions(
            [self.sanitize_name(m.get("name", "")) for m in materials],
            [m.get("name") for m in materials],
            "Materials",
        )
        self.reject_name_collisions(
            [self.sanitize_name(s.get("name", f"sup_{i}")) for i, s in enumerate(suppliers)],
            [s.get("name") for s in suppliers],
            "Suppliers",
        )

        required: dict[str, float] = {}
        label: dict[str, str] = {}
        for mat in materials:
            key = self.sanitize_name(mat.get("name", ""))
            # "or 0.0" turned a demand key this generator does not recognise
            # into a requirement of zero. That pinned the purchase variable's
            # upper bound to 0 and skipped the requirement row, so a card whose
            # whole job is to buy 80 tonnes of steel answered "buy nothing,
            # cost 0, optimal". Every other missing field here raises.
            demand = self.first_number(mat, self._DEMAND_KEYS)
            if demand is None:
                raise ValueError(
                    f"Material '{mat.get('name', key)}' states no requirement. "
                    f"Expected one of: {', '.join(self._DEMAND_KEYS)}. "
                    f"Fields present: {sorted(mat)}."
                )
            required[key] = demand
            label[key] = str(mat.get("name", key))

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        cost_terms: list[str] = []
        qty_by_material: dict[str, list[str]] = {}
        unquoted: list[str] = []

        for i, sup in enumerate(suppliers):
            offered = self._offered_material(sup)
            mat_key = self.sanitize_name(offered) if offered else ""
            if mat_key not in required:
                unquoted.append(f"{sup.get('name', f'supplier {i}')} -> {offered}")
                continue

            sup_name = self.sanitize_name(sup.get("name", f"sup_{i}"))
            qty = f"qty_{sup_name}"
            price = self.first_number(sup, self._PRICE_KEYS)
            if price is None:
                raise ValueError(
                    f"Supplier '{sup.get('name', sup_name)}' quotes no price. "
                    f"Expected one of: {', '.join(self._PRICE_KEYS)}."
                )
            capacity = self.first_number(sup, ("max_capacity", "capacity", "max_supply"))
            delivery = self.first_number(sup, ("delivery_cost", "fixed_cost", "setup_cost"))
            min_order = self.first_number(sup, ("min_order", "minimum_order", "min_order_qty"))

            # Without a stated capacity the requirement itself bounds the order:
            # buying more of a material than is required is never optimal here.
            bound = capacity if capacity is not None else required[mat_key]
            variables.append(
                Variable(name=qty, type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=bound)
            )
            cost_terms.append(f"{price}*{qty}")
            qty_by_material.setdefault(mat_key, []).append(qty)

            if delivery or min_order:
                use = f"use_{sup_name}"
                variables.append(Variable(name=use, type=VariableType.BINARY))
                if delivery:
                    cost_terms.append(f"{delivery}*{use}")
                # Ordering anything switches the supplier on, so the fixed
                # charge cannot be dodged.
                constraints.append(
                    Constraint(name=f"link_{sup_name}", expression=f"{qty} - {bound}*{use} <= 0")
                )
                if min_order:
                    constraints.append(
                        Constraint(
                            name=f"minorder_{sup_name}",
                            expression=f"{qty} - {min_order}*{use} >= 0",
                        )
                    )

        if not variables:
            raise ValueError(
                "No supplier quotes matched a material. Suppliers name their material in "
                f"one of {self._OFFERED_KEYS}; materials seen: {sorted(label.values())}."
            )
        # A quote for something nobody asked for is a data error, not a row to
        # drop in silence.
        if unquoted:
            raise ValueError(
                f"{len(unquoted)} supplier quote(s) name a material that is not in the "
                f"requirements list: {'; '.join(unquoted[:5])}"
            )

        for mat_key, need in required.items():
            terms = qty_by_material.get(mat_key)
            if not terms:
                raise ValueError(f"No supplier quotes for required material '{label[mat_key]}'.")
            if need > 0:
                constraints.append(
                    Constraint(
                        name=f"require_{mat_key}",
                        expression=f"{' + '.join(terms)} >= {need}",
                    )
                )

        return OptimizationProblem(
            name="supplier_quotes",
            description=(
                f"Buy {len(materials)} materials from {len(variables)} supplier quotes "
                f"at least total cost"
            ),
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression=" + ".join(cost_terms)),
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
        # Explicit pair bookkeeping — matching rows by name prefix/suffix put
        # variables in the wrong rows whenever one name extends another
        # ("steel" also matched every "…_stainless_steel" variable).
        vars_by_material: dict[str, list[str]] = {}
        vars_by_supplier: dict[str, list[str]] = {}

        # Build variable for each (supplier, material) pair
        for sup in suppliers:
            sup_name = self.sanitize_name(sup.get("name", f"sup_{len(variables)}"))
            pricing = sup.get("pricing", {})

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
                vars_by_material.setdefault(mat_name, []).append(var_name)
                vars_by_supplier.setdefault(sup_name, []).append(var_name)

        constraints: list[Constraint] = []

        # Demand satisfaction per material
        for mat in materials:
            mat_name = self.sanitize_name(mat.get("name", ""))
            demand = float(mat.get("demand", 0))
            mat_terms = vars_by_material.get(mat_name, [])
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
                sup_terms = vars_by_supplier.get(sup_name, [])
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
