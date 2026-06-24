"""Knapsack generator — item selection problems with capacity constraints.

Supports multiple input formats:
- Standard: ``items`` list with ``value``/``weight`` keys, ``capacity`` scalar
- Domain-specific: auto-detects the item list and infers value/weight fields
  from common patterns (cost, price, revenue, benefit, etc.)
"""

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

# Field name patterns for auto-detecting value and weight (cost) fields
_VALUE_FIELDS = [
    "value",
    "revenue",
    "benefit",
    "reach_per_unit",
    "benefit_per_dollar",
    "monthly_rent",
    "foot_traffic_score",
    "profit",
]
_WEIGHT_FIELDS = [
    "weight",
    "cost",
    "cost_per_unit",
    "price",
    "price_per_unit",
    "mass_kg",
    "space_sqm",
    "bandwidth",
    "size",
]
# Capacity-like scalar fields
_CAPACITY_FIELDS = [
    "capacity",
    "total_budget",
    "max_mass",
    "max_volume",
    "total_space",
    "link_capacity",
    "budget",
]


def _find_items_list(user_input: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Find the primary list of items in the input dict.

    Returns (items_list, key_name). Prefers ``items``, otherwise picks the
    first list-of-dicts key.
    """
    if "items" in user_input and isinstance(user_input["items"], list):
        return user_input["items"], "items"

    for key, val in user_input.items():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val, key

    return [], ""


def _find_field(item: dict[str, Any], candidates: list[str], default: float = 1.0) -> float:
    """Return the first matching field value from *candidates* in *item*."""
    for field in candidates:
        if field in item and item[field] is not None:
            return float(item[field])
    return default


def _find_capacity(user_input: dict[str, Any]) -> float:
    """Extract the capacity / budget scalar from the input."""
    for field in _CAPACITY_FIELDS:
        if field in user_input and not isinstance(user_input[field], (list, dict)):
            return float(user_input[field])
    return 100.0


class KnapsackGenerator(BaseGenerator):
    """Generate knapsack problems (0-1 or bounded).

    Automatically maps domain-specific input formats to the standard
    knapsack formulation by detecting item lists and value/weight fields.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        items, _key = _find_items_list(user_input)
        capacity = _find_capacity(user_input)

        variables: list[Variable] = []
        value_terms: list[str] = []
        weight_terms: list[str] = []

        for i, item in enumerate(items):
            name = self.sanitize_name(item.get("name", f"item_{i}"))
            value = _find_field(item, _VALUE_FIELDS)
            weight = _find_field(item, _WEIGHT_FIELDS)

            variables.append(Variable(name=name, type=VariableType.BINARY))

            value_terms.append(f"{value}*{name}")
            weight_terms.append(f"{weight}*{name}")

        if not variables:
            raise ValueError(
                "Knapsack generator requires at least one item. "
                "Provide an 'items' list or a domain-specific list of selectable objects."
            )

        constraints = [
            Constraint(
                name="capacity",
                expression=f"{' + '.join(weight_terms)} <= {capacity}",
            )
        ]

        return OptimizationProblem(
            name="knapsack",
            description=f"Select items to maximize value within capacity {capacity}",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(value_terms),
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
