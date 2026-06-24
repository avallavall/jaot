"""Cutting stock generator — 1D cutting stock problems with column generation patterns."""

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


class CuttingStockGenerator(BaseGenerator):
    """Generate 1D cutting stock problems.

    Given a stock length and item demands, generate basic cutting patterns
    and minimize the number of stock pieces used.

    Uses a simple enumeration of single-item patterns for the initial formulation.
    For large instances, column generation should be used (handled at solver level).
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        stock_length = user_input.get("stock_length", user_input.get("roll_width", 100))
        items = user_input.get("items", user_input.get("orders", user_input.get("pieces", [])))

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        obj_terms: list[str] = []

        # Generate basic patterns: each pattern cuts as many of one item as possible
        patterns: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            i_name = self.sanitize_name(item.get("name", f"item_{i}"))
            length = item.get("length", item.get("width", 1))
            max_per_stock = int(stock_length // length) if length > 0 else 0

            # Single-item pattern
            if max_per_stock > 0:
                pattern = {"items": {i_name: max_per_stock}, "idx": len(patterns)}
                patterns.append(pattern)

        # Also generate pair patterns for each combination
        for i, item_i in enumerate(items):
            for j, item_j in enumerate(items):
                if j <= i:
                    continue
                i_name = self.sanitize_name(item_i.get("name", f"item_{i}"))
                j_name = self.sanitize_name(item_j.get("name", f"item_{j}"))
                li = item_i.get("length", item_i.get("width", 1))
                lj = item_j.get("length", item_j.get("width", 1))

                if li + lj <= stock_length:
                    count_i = 1
                    count_j = int((stock_length - li) // lj) if lj > 0 else 0
                    if count_j > 0:
                        pattern = {
                            "items": {i_name: count_i, j_name: count_j},
                            "idx": len(patterns),
                        }
                        patterns.append(pattern)

        # Variable per pattern: how many times to use this pattern
        for p in patterns:
            var_name = f"pattern_{p['idx']}"
            max_uses = max(item.get("demand", 10) for item in items) if items else 10

            variables.append(
                Variable(
                    name=var_name,
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=max_uses,
                )
            )
            obj_terms.append(var_name)

        # Demand constraints: for each item, patterns must yield enough
        for i, item in enumerate(items):
            i_name = self.sanitize_name(item.get("name", f"item_{i}"))
            demand = item.get("demand", 1)

            demand_terms: list[str] = []
            for p in patterns:
                if i_name in p["items"]:
                    count = p["items"][i_name]
                    demand_terms.append(f"{count}*pattern_{p['idx']}")

            if demand_terms:
                constraints.append(
                    Constraint(
                        name=f"demand_{i_name}",
                        expression=f"{' + '.join(demand_terms)} >= {demand}",
                    )
                )

        return OptimizationProblem(
            name="cutting_stock",
            description=(f"Cut {len(items)} item types from stock of length {stock_length}"),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(obj_terms) if obj_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
