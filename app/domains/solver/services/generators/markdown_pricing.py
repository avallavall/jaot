"""Markdown pricing generator — retail clearance optimization.

Selects a discount level for each product from discrete options
to maximize clearance revenue, considering demand elasticity
and inventory constraints.
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


class MarkdownPricingGenerator(BaseGenerator):
    """Generate markdown pricing problems.

    Uses discrete discount levels (0%, 10%, 20%, ..., 70%) per product
    to avoid nonlinear demand-price interaction. Binary selection
    of one markdown level per product.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        products = find_list_field(user_input, ["products", "items", "skus", "inventory"])
        if not products:
            raise ValueError(
                f"Markdown pricing requires a products list. Got keys: {list(user_input.keys())}"
            )

        # Discount levels (default: 0% to 70% in 10% steps)
        discount_levels = user_input.get(
            "discount_levels", params.get("discount_levels", [0, 10, 20, 30, 40, 50, 60, 70])
        )
        min_clearance = float(user_input.get("min_clearance_fraction", 0))

        variables: list[Variable] = []
        revenue_terms: list[str] = []
        # Cache demand per (product_name, discount) for reuse in clearance constraint
        demand_cache: dict[str, float] = {}

        for i, prod in enumerate(products):
            p_name = self.sanitize_name(prod.get("name", f"prod_{i}"))
            base_price = float(prod.get("base_price", prod.get("price", 0)))
            inventory = int(prod.get("inventory", prod.get("stock", 0)))
            elasticity = float(prod.get("elasticity", prod.get("demand_elasticity", 1.0)))
            base_demand = float(
                prod.get("base_demand", prod.get("expected_demand", inventory * 0.5))
            )

            for disc in discount_levels:
                disc_frac = disc / 100.0
                sale_price = base_price * (1 - disc_frac)
                demand = min(base_demand * (1 + elasticity * disc_frac), inventory)
                revenue = sale_price * demand

                var_name = f"{p_name}_d{disc}"
                variables.append(Variable(name=var_name, type=VariableType.BINARY))
                revenue_terms.append(f"{round(revenue, 2)}*{var_name}")
                demand_cache[var_name] = demand

        constraints: list[Constraint] = []

        # Exactly one discount level per product
        for i, prod in enumerate(products):
            p_name = self.sanitize_name(prod.get("name", f"prod_{i}"))
            level_vars = [f"{p_name}_d{d}" for d in discount_levels]
            constraints.append(
                Constraint(
                    name=f"one_level_{p_name}",
                    expression=f"{' + '.join(level_vars)} == 1",
                )
            )

        # Minimum clearance fraction (optional)
        if min_clearance > 0:
            clearance_terms = [f"{round(demand_cache[v.name], 2)}*{v.name}" for v in variables]
            total_inventory = sum(int(p.get("inventory", p.get("stock", 0))) for p in products)
            if clearance_terms and total_inventory > 0:
                constraints.append(
                    Constraint(
                        name="min_clearance",
                        expression=f"{' + '.join(clearance_terms)} >= {min_clearance * total_inventory}",
                    )
                )

        return OptimizationProblem(
            name="markdown_pricing",
            description=f"Optimize markdowns for {len(products)} products across {len(discount_levels)} discount levels",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(revenue_terms) if revenue_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
