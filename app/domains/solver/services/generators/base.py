"""
Base generator class and registry for parametric problem generators.

All generators extend BaseGenerator and register in GeneratorRegistry.
Templates configure base generators with domain-specific parameters.
"""

import re
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, cast

from app.schemas.optimization import Constraint, OptimizationProblem


class BaseGenerator(ABC):
    """Abstract base for parametric problem generators."""

    @abstractmethod
    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        """Generate an optimization problem from user input and template params.

        Args:
            user_input: User-provided input data (items, workers, etc.)
            params: Generator parameters from template YAML for domain customization

        Returns:
            OptimizationProblem ready for solving
        """
        ...

    def sanitize_name(self, name: str) -> str:
        """Sanitize a name to be a valid variable identifier."""
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(name))
        if not sanitized or sanitized == "_":
            sanitized = "unnamed"
        if sanitized[0].isdigit():
            sanitized = f"v_{sanitized}"
        return sanitized.lower()

    def build_warm_start(
        self, user_input: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, float] | None:
        """Build a heuristic warm start solution for the solver.

        Override in subclasses to provide a greedy initial solution.
        Returns a dict mapping variable names to float values, or None.
        The solver will use this as a starting point for branch-and-bound.
        """
        return None

    def validate_input(self, user_input: dict[str, Any], required_fields: list[str]) -> None:
        """Validate user input has required fields (non-None and non-empty).

        Raises:
            ValueError: If any required field is missing, None, or empty.
        """
        missing = []
        for f in required_fields:
            val = user_input.get(f)
            if val is None or val == [] or val == "" or val == {}:
                missing.append(f)
        if missing:
            raise ValueError(
                f"Missing or empty required fields: {', '.join(missing)}. "
                f"Got keys: {list(user_input.keys())}"
            )


class GenericGenerator(BaseGenerator):
    """Improved generic generator with validation and clear error messages.

    Not just raw pass-through: validates required fields and provides
    helpful error messages for missing or malformed fields.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        """Generate a problem from direct specification with validation."""
        if "variables" not in user_input or not user_input["variables"]:
            raise ValueError(
                "Missing 'variables' field. A generic problem requires at least one variable. "
                'Example: [{"name": "x", "type": "continuous", "lower_bound": 0}]'
            )

        if "objective" not in user_input or not user_input["objective"]:
            raise ValueError(
                "Missing 'objective' field. A generic problem requires an objective. "
                'Example: {"sense": "maximize", "expression": "3*x + 2*y"}'
            )

        return OptimizationProblem(**user_input)


def find_list_field(
    user_input: dict[str, Any],
    preferred_keys: list[str],
) -> list[dict[str, Any]]:
    """Auto-detect a list-of-dicts field from *user_input*.

    Tries *preferred_keys* first, then falls back to the first list-of-dicts
    value found in the input.
    """
    for key in preferred_keys:
        if key in user_input and isinstance(user_input[key], list):
            return cast(list[dict[str, Any]], user_input[key])

    for val in user_input.values():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return cast(list[dict[str, Any]], val)

    return []


def safe_float(value: Any, field_name: str = "field") -> float:
    """Convert value to float, rejecting NaN/Inf with a clear error."""
    try:
        result = float(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Cannot convert {field_name}={value!r} to float") from e
    if result != result or result == float("inf") or result == float("-inf"):  # NaN/Inf check
        raise ValueError(f"Invalid numeric value for {field_name}: {result}")
    return result


def find_scalar_field(
    user_input: dict[str, Any],
    preferred_keys: list[str],
    default: float = 0.0,
) -> float:
    """Auto-detect a scalar (non-list, non-dict) field from *user_input*."""
    for key in preferred_keys:
        if key in user_input and not isinstance(user_input[key], (list, dict)):
            return safe_float(user_input[key], key)
    return default


# Pre-optimization utilities (Pilar 2.5)
# Generic functions any generator can use to reduce problem size.


def build_reachable_nodes(
    arcs: list[tuple[str, str, int]],
) -> defaultdict[int, set[str]]:
    """Compute which nodes each vehicle can reach from the arc set.

    Returns defaultdict {vehicle_index: {node_id, ...}}. Safe to subscript
    with any vehicle index — returns empty set for vehicles with no arcs.
    """
    result: defaultdict[int, set[str]] = defaultdict(set)
    for i, j, k in arcs:
        result[k].add(i)
        result[k].add(j)
    return result


def compute_arc_big_m(
    node_i: dict[str, Any],
    node_j: dict[str, Any],
    travel_time: float,
    planning_horizon: float,
) -> float:
    """Compute per-arc big-M for time propagation constraints.

    For the rearranged form: S_ik + M*X_ijk - S_jk <= M - s_i - t_ij
    When X=0, non-binding requires: M >= max(S_ik) + s_i + t_ij - min(S_jk)

    With S_ik in [a_i, horizon] and S_jk in [a_j, horizon]:
      worst case: S_ik = horizon, S_jk = a_j
      => M >= horizon + s_i + t_ij - a_j
    The +1.0 buffer ensures strict inequality (numerical safety).

    Tighter than a global M when a_j > 0.
    """
    a_j = node_j.get("earliest", 0)
    s_i = node_i.get("service_time", 0)
    m = planning_horizon + s_i + travel_time - a_j + 1.0
    if m <= 0:
        raise ValueError(
            f"compute_arc_big_m: non-positive M={m:.2f}. "
            f"earliest_j={a_j} > horizon={planning_horizon}? Check units."
        )
    return m


def add_symmetry_breaking(
    constraints: list[Constraint],
    group_vars: dict[int, str],
    group_indices: list[list[int]],
) -> None:
    """Add symmetry-breaking constraints for identical resources in groups.

    For each group of identical resource indices [k1, k2, k3, ...],
    adds: var[k1] >= var[k2] >= var[k3] >= ...
    This eliminates factorial symmetric solutions in branch-and-bound.

    Only use when resources within a group are truly interchangeable
    (same cost, capacity, and compatibility constraints).
    """
    for group in group_indices:
        if not group or len(group) < 2:
            continue
        for i in range(len(group) - 1):
            k1, k2 = group[i], group[i + 1]
            if k1 in group_vars and k2 in group_vars:
                constraints.append(
                    Constraint(
                        name=f"sym_break_{k1}_{k2}",
                        expression=f"{group_vars[k1]} + -1*{group_vars[k2]} >= 0",
                    )
                )


class GeneratorRegistry:
    """Registry mapping generator type strings to generator classes."""

    _generators: dict[str, type[BaseGenerator]] = {}

    @classmethod
    def register(cls, name: str, generator_class: type[BaseGenerator]) -> None:
        """Register a generator class under a name."""
        cls._generators[name] = generator_class

    @classmethod
    def get(cls, name: str) -> BaseGenerator:
        """Get a generator instance by name. Falls back to GenericGenerator."""
        generator_class = cls._generators.get(name, GenericGenerator)
        return generator_class()

    @classmethod
    def list_generators(cls) -> list[str]:
        """List all registered generator names."""
        return list(cls._generators.keys())
