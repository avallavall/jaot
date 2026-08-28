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

    Given a stock length and item demands, enumerate every maximal cutting
    pattern (up to ``MAX_PATTERNS``) and minimize the number of stock pieces
    used. With the full maximal-pattern set the ILP optimum is the true
    cutting-stock optimum; if the cap trips, the truncation is stated in the
    problem description rather than silently sealed as "optimal".
    """

    # Enumeration budget: beyond this many patterns the set is truncated and the
    # problem description says so — "optimal" must never quietly mean "optimal
    # over the patterns we happened to write down".
    MAX_PATTERNS = 5000

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        stock_length = user_input.get("stock_length", user_input.get("roll_width", 100))
        items = user_input.get("items", user_input.get("orders", user_input.get("pieces", [])))

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        obj_terms: list[str] = []

        # Enumerate every MAXIMAL cutting pattern (no further piece fits). The
        # previous set — single-item patterns plus one arbitrary pair shape —
        # sealed "optimal" over a pattern set that missed most of the real ones.
        # At catalog scale full enumeration is small; the cap keeps adversarial
        # inputs bounded, and tripping it is disclosed in the description.
        names: list[str] = []
        lengths: list[float] = []
        for i, item in enumerate(items):
            length = item.get("length", item.get("width", 1))
            if length and length > 0 and length <= stock_length:
                names.append(self.sanitize_name(item.get("name", f"item_{i}")))
                lengths.append(float(length))

        patterns: list[dict[str, Any]] = []
        truncated = False

        def enumerate_patterns(idx: int, counts: list[int], space: float) -> None:
            nonlocal truncated
            if truncated:
                return
            if idx == len(names):
                if any(counts) and all(space < ln for ln in lengths):
                    if len(patterns) >= self.MAX_PATTERNS:
                        truncated = True
                        return
                    patterns.append(
                        {
                            "items": {n: c for n, c in zip(names, counts, strict=True) if c},
                            "idx": len(patterns),
                        }
                    )
                return
            max_count = int(space // lengths[idx])
            # Descend from the fullest use of this item so maximal patterns
            # surface first if the cap ever trips.
            for count in range(max_count, -1, -1):
                counts[idx] = count
                enumerate_patterns(idx + 1, counts, space - count * lengths[idx])
            counts[idx] = 0

        if names:
            enumerate_patterns(0, [0] * len(names), float(stock_length))

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
            # Both shipped cards write "quantity", not "demand", so every order
            # silently became a demand of 1: the plan cut one of each piece
            # instead of the ten, eight, six, four and three that were asked
            # for, and still came back "optimal".
            demand = next(
                (
                    float(item[key])
                    for key in ("demand", "quantity", "qty", "required", "count")
                    if item.get(key) is not None
                ),
                None,
            )
            if demand is None:
                raise ValueError(
                    f"Cut item '{item.get('name', i)}' states no quantity. "
                    "Expected one of: demand, quantity, qty, required, count."
                )

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

        description = f"Cut {len(items)} item types from stock of length {stock_length}"
        if truncated:
            description += (
                f" (pattern set truncated at {self.MAX_PATTERNS}: the solution is optimal "
                "over the enumerated patterns, not over all possible ones)"
            )

        return OptimizationProblem(
            name="cutting_stock",
            description=description,
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(obj_terms) if obj_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
