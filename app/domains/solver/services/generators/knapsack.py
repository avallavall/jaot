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


def _has_field(item: dict[str, Any], candidates: list[str]) -> bool:
    return any(field in item and item[field] is not None for field in candidates)


#: Limits that come in matched pairs: the scalar cap on the input, and the
#: per-item field it applies to. A launch has a mass budget AND a volume
#: budget; writing only the first one drops half the problem.
_LIMIT_DIMENSIONS: list[tuple[str, list[str], str]] = [
    ("mass", ["max_mass", "mass_capacity"], "mass_kg"),
    ("volume", ["max_volume", "volume_capacity"], "volume_m3"),
    ("space", ["total_space", "max_space"], "space_sqm"),
]

#: A target the selection must reach turns the knapsack around: instead of
#: "most value inside a budget" it becomes "least cost that reaches the
#: target". Regulation-driven cards state a target, not a budget.
_TARGET_FIELDS = ["min_value", "target_value", "required_value", "min_total_value"]


def _find_scalar(user_input: dict[str, Any], fields: list[str]) -> float | None:
    for field in fields:
        value = user_input.get(field)
        if value is not None and not isinstance(value, (list, dict)):
            return float(value)
    return None


def _find_capacity(user_input: dict[str, Any]) -> float | None:
    """Extract the capacity / budget scalar from the input."""
    return _find_scalar(user_input, _CAPACITY_FIELDS)


class KnapsackGenerator(BaseGenerator):
    """Generate knapsack problems (0-1 or bounded).

    Automatically maps domain-specific input formats to the standard
    knapsack formulation by detecting item lists and value/weight fields.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        items, key = _find_items_list(user_input)
        if not items:
            raise ValueError(
                "Knapsack generator requires at least one item. "
                "Provide an 'items' list or a domain-specific list of selectable objects."
            )

        # A value or a weight that no item carries used to default to 1.0 per
        # item, which turns the objective into a plain count of selected items
        # and the capacity row into a limit on how many fit. Both look like a
        # working model and answer nothing.
        if not any(_has_field(item, _VALUE_FIELDS) for item in items):
            raise ValueError(
                f"No item in '{key or 'items'}' carries a value field. "
                f"Expected one of: {', '.join(_VALUE_FIELDS)}."
            )
        if not any(_has_field(item, _WEIGHT_FIELDS) for item in items):
            raise ValueError(
                f"No item in '{key or 'items'}' carries a weight or cost field. "
                f"Expected one of: {', '.join(_WEIGHT_FIELDS)}."
            )

        variables: list[Variable] = []
        value_terms: list[str] = []
        weight_terms: list[str] = []
        dimension_terms: dict[str, list[str]] = {}
        constraints_from_min_totals: list[Constraint] = []

        for i, item in enumerate(items):
            name = self.sanitize_name(item.get("name", f"item_{i}"))
            value = _find_field(item, _VALUE_FIELDS)
            weight = _find_field(item, _WEIGHT_FIELDS)

            # A channel you buy 5000 impressions of is not a yes/no item. When
            # the card states how many units may be bought, the variable counts
            # them: with a binary, min_units and max_units could not reach the
            # model at all and the answer was "run this channel" with no volume.
            low = item.get("min_units", item.get("min_quantity"))
            high = item.get("max_units", item.get("max_quantity"))
            if low is not None or high is not None:
                variables.append(
                    Variable(
                        name=name,
                        type=VariableType.INTEGER,
                        lower_bound=float(low) if low is not None else 0,
                        upper_bound=float(high) if high is not None else None,
                    )
                )
            else:
                variables.append(Variable(name=name, type=VariableType.BINARY))

            value_terms.append(f"{value}*{name}")
            weight_terms.append(f"{weight}*{name}")

            for label, _cap_fields, item_field in _LIMIT_DIMENSIONS:
                if item.get(item_field) is not None:
                    dimension_terms.setdefault(label, []).append(
                        f"{float(item[item_field])}*{name}"
                    )

        target = _find_scalar(user_input, _TARGET_FIELDS)
        capacity = _find_capacity(user_input)

        # A floor on the total of some other item field. A shopping centre
        # maximizes rent, but the mix still has to pull enough footfall, and
        # that second figure was sitting in the data doing nothing.
        for field, floor in (params.get("min_totals") or {}).items():
            terms = [
                f"{float(item[field])}*{self.sanitize_name(item.get('name', f'item_{i}'))}"
                for i, item in enumerate(items)
                if item.get(field) is not None
            ]
            if not terms:
                raise ValueError(f"min_totals names '{field}' but no item carries it.")
            constraints_from_min_totals.append(
                Constraint(name=f"min_{field}", expression=f"{' + '.join(terms)} >= {float(floor)}")
            )

        constraints: list[Constraint] = list(constraints_from_min_totals)
        # Every stated limit becomes a row, not just the first one found.
        written: set[str] = set()
        for label, cap_fields, _item_field in _LIMIT_DIMENSIONS:
            limit = _find_scalar(user_input, cap_fields)
            terms = dimension_terms.get(label)
            if limit is not None and terms:
                constraints.append(
                    Constraint(name=f"limit_{label}", expression=f"{' + '.join(terms)} <= {limit}")
                )
                written.update(cap_fields)

        # The generic weight/capacity row, unless a named dimension already
        # covered that same scalar (mass_kg is also matched as a weight).
        if capacity is not None and not any(
            field in written
            for field in _CAPACITY_FIELDS
            if _find_scalar(user_input, [field]) == capacity
        ):
            constraints.append(
                Constraint(name="capacity", expression=f"{' + '.join(weight_terms)} <= {capacity}")
            )

        if target is not None:
            constraints.append(
                Constraint(name="reach_target", expression=f"{' + '.join(value_terms)} >= {target}")
            )
            return OptimizationProblem(
                name="covering_knapsack",
                description=f"Select items reaching a total value of {target} at least cost",
                variables=variables,
                objective=Objective(
                    sense=ObjectiveSense.MINIMIZE, expression=" + ".join(weight_terms)
                ),
                constraints=constraints,
                options=SolverOptions(time_limit_seconds=30),
            )

        if not constraints:
            raise ValueError(
                "Knapsack generator found no capacity, limit or target to respect. "
                f"Expected one of: {', '.join(_CAPACITY_FIELDS + _TARGET_FIELDS)}."
            )

        return OptimizationProblem(
            name="knapsack",
            description=f"Select items to maximize value within {len(constraints)} limit(s)",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(value_terms),
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
