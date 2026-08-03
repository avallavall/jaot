"""Period selection generator — place items into periods under per-period capacity.

The honest model behind three card families the scheduling generator could not
tell (their inputs are one list of items and a horizon, not workers and shifts):

- ``select`` mode (default): choose WHICH items to do and WHEN — each item at
  most once — maximizing total value. Open-pit blocks against plant capacity
  (value net of cost, optional per-period minimum grade, optional precedence
  via ``requires``), forest stands against a per-period area cap (revenue =
  volume × price, optional ``adjacent_to`` exclusions). ``discount_rate``
  turns the objective into an NPV.
- ``assign`` mode (``generator_params: {mode: assign}``): every item must land
  in exactly one admissible period — track sections into possession windows,
  each window with an hour budget and each section with a deadline. The
  objective sends the most heavily used sections to the earliest feasible
  windows (value × period order, minimized); with every item mandatory, total
  disruption itself is a constant.
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

_WEIGHT_KEYS = ["tonnage", "area_ha", "duration_hours", "duration", "weight"]
_DEADLINE_KEYS = ["deadline_day", "deadline_period", "deadline"]


def _item_weight(item: dict[str, Any]) -> float:
    for key in _WEIGHT_KEYS:
        if item.get(key) is not None:
            return float(item[key])
    return 1.0


def _item_value(item: dict[str, Any]) -> float:
    """The item's contribution: net value, or volume × unit price, or a plain field."""
    if item.get("value") is not None:
        return float(item["value"]) - float(item.get("cost", 0))
    if item.get("timber_volume") is not None and item.get("revenue_per_m3") is not None:
        return float(item["timber_volume"]) * float(item["revenue_per_m3"])
    for key in ("profit", "revenue", "trains_affected"):
        if item.get(key) is not None:
            return float(item[key])
    return 1.0


class PeriodSelectionGenerator(BaseGenerator):
    """Generate item-to-period selection/assignment problems."""

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        items = find_list_field(user_input, ["blocks", "stands", "sections", "parcels", "items"])
        if not items:
            raise ValueError(
                f"Period selection requires an items list (blocks, stands, sections…). "
                f"Got keys: {list(user_input.keys())}"
            )
        mandatory = params.get("mode") == "assign"

        # Periods: an explicit windows list (each with its own capacity and
        # day), or a count plus one shared capacity.
        windows = find_list_field(
            user_input, ["maintenance_windows", "windows", "periods"], fallback=False
        )
        shared_capacity = float(
            user_input.get(
                "plant_capacity",
                user_input.get("max_area_per_period", user_input.get("capacity_per_period", 0)),
            )
        )
        if windows:
            periods = [
                {
                    "name": self.sanitize_name(
                        w.get("name", f"w{i + 1}_day_{w.get('day', i + 1)}")
                    ),
                    "capacity": float(
                        w.get("capacity", w.get("duration_hours", shared_capacity or 0))
                    ),
                    "order": float(w.get("day", w.get("period", i + 1))),
                }
                for i, w in enumerate(windows)
            ]
        else:
            num_periods = int(user_input.get("num_periods", user_input.get("periods", 1)))
            periods = [
                {"name": f"p{p + 1}", "capacity": shared_capacity, "order": float(p + 1)}
                for p in range(num_periods)
            ]

        discount_rate = float(user_input.get("discount_rate", 0))
        min_grade = float(user_input.get("min_grade", 0))

        names: list[str] = []
        weights: list[float] = []
        values: list[float] = []
        deadlines: list[float | None] = []
        for i, item in enumerate(items):
            names.append(self.sanitize_name(item.get("name", f"item_{i}")))
            weights.append(_item_weight(item))
            values.append(_item_value(item))
            deadline = next(
                (float(item[k]) for k in _DEADLINE_KEYS if item.get(k) is not None), None
            )
            deadlines.append(deadline)

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        obj_terms: list[str] = []
        # x_{item}_{period}, only for admissible periods (deadline respected).
        vars_of_item: dict[str, list[str]] = {}
        vars_of_period: dict[str, list[tuple[int, str]]] = {p["name"]: [] for p in periods}

        for i, name in enumerate(names):
            item_vars: list[str] = []
            for p_idx, period in enumerate(periods):
                if deadlines[i] is not None and period["order"] > deadlines[i]:
                    continue
                var_name = f"x_{name}_{period['name']}"
                variables.append(Variable(name=var_name, type=VariableType.BINARY))
                item_vars.append(var_name)
                vars_of_period[period["name"]].append((i, var_name))
                if mandatory:
                    # Busiest items earliest; ties cost nothing.
                    obj_terms.append(f"{values[i] * period['order']}*{var_name}")
                else:
                    discounted = values[i] / ((1 + discount_rate) ** p_idx)
                    obj_terms.append(f"{round(discounted, 6)}*{var_name}")
            if not item_vars:
                raise ValueError(
                    f"Item '{names[i]}' has no admissible period: its deadline "
                    f"({deadlines[i]}) precedes every available window."
                )
            vars_of_item[name] = item_vars
            constraints.append(
                Constraint(
                    name=f"once_{name}",
                    expression=f"{' + '.join(item_vars)} {'==' if mandatory else '<='} 1",
                )
            )

        # Per-period weighted capacity.
        for period in periods:
            if period["capacity"] <= 0:
                continue
            terms = [f"{weights[i]}*{v}" for i, v in vars_of_period[period["name"]]]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"capacity_{period['name']}",
                        expression=f"{' + '.join(terms)} <= {period['capacity']}",
                    )
                )

        # Minimum average grade per period (mining): the blend of blocks
        # processed in one period must reach the grade floor. Linearized as
        # sum((grade_i - min_grade) * tonnage_i * x_ip) >= 0.
        if min_grade > 0:
            for period in periods:
                terms = []
                for i, v in vars_of_period[period["name"]]:
                    grade = float(items[i].get("grade", 0))
                    coef = (grade - min_grade) * weights[i]
                    if abs(coef) > 1e-12:
                        terms.append(f"{coef}*{v}")
                if terms:
                    constraints.append(
                        Constraint(
                            name=f"grade_{period['name']}",
                            expression=f"{' + '.join(terms)} >= 0",
                        )
                    )

        # Precedence: a required item must be placed in the same or an earlier
        # period (mining: the block above comes out first).
        name_by_raw = {str(item.get("name", f"item_{i}")): names[i] for i, item in enumerate(items)}
        for i, item in enumerate(items):
            for req_raw in item.get("requires", item.get("predecessors", [])) or []:
                req = name_by_raw.get(str(req_raw), self.sanitize_name(str(req_raw)))
                if req not in vars_of_item or req == names[i]:
                    continue
                for period in periods:
                    var_name = f"x_{names[i]}_{period['name']}"
                    if var_name not in vars_of_item[names[i]]:
                        continue
                    earlier = [
                        v
                        for p2 in periods
                        if p2["order"] <= period["order"]
                        for v in [f"x_{req}_{p2['name']}"]
                        if v in vars_of_item[req]
                    ]
                    if earlier:
                        constraints.append(
                            Constraint(
                                name=f"prec_{req}_{names[i]}_{period['name']}",
                                expression=f"{' + '.join(earlier)} - {var_name} >= 0",
                            )
                        )

        # Mutual exclusion per period (forestry adjacency).
        seen_pairs: set[tuple[str, str]] = set()
        for i, item in enumerate(items):
            for adj_raw in item.get("adjacent_to", []) or []:
                adj = name_by_raw.get(str(adj_raw), self.sanitize_name(str(adj_raw)))
                if adj not in vars_of_item or adj == names[i]:
                    continue
                pair = tuple(sorted((names[i], adj)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                for period in periods:
                    a = f"x_{pair[0]}_{period['name']}"
                    b = f"x_{pair[1]}_{period['name']}"
                    if a in vars_of_item[pair[0]] and b in vars_of_item[pair[1]]:
                        constraints.append(
                            Constraint(
                                name=f"adj_{pair[0]}_{pair[1]}_{period['name']}",
                                expression=f"{a} + {b} <= 1",
                            )
                        )

        return OptimizationProblem(
            name="period_assignment" if mandatory else "period_selection",
            description=(
                f"{'Assign' if mandatory else 'Select'} {len(items)} items "
                f"across {len(periods)} periods"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE if mandatory else ObjectiveSense.MAXIMIZE,
                expression=" + ".join(obj_terms) if obj_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
