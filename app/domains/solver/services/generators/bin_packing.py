"""Bin packing generator — minimize bins used for items."""

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


class BinPackingGenerator(BaseGenerator):
    """Generate bin packing problems.

    Minimizes the number of bins used. Uses binary variables:
    - y_j = 1 if bin j is used
    - x_i_j = 1 if item i is placed in bin j
    """

    #: An item's measure paired with the container limit that caps it. A ship's
    #: container has TWO: it fills up on volume or on weight, whichever comes
    #: first, and only writing one of them loads cargo the ship cannot carry.
    _DIMENSIONS = (
        ("volume", "max_volume"),
        ("volume_teu", "capacity_teu"),
        ("weight", "max_weight"),
        ("size", "capacity"),
        ("area", "max_area"),
    )
    _VALUE_KEYS = ("value", "revenue", "priority", "profit")

    @staticmethod
    def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if row.get(key) is not None:
                return float(row[key])
        return None

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        items = next(
            (user_input[k] for k in ("items", "shipments", "cargo", "loads") if user_input.get(k)),
            [],
        )
        if not items:
            raise ValueError(
                f"Bin packing requires an items list. Got keys: {list(user_input.keys())}"
            )

        # Named containers with their own limits are a different question from
        # "how few identical bins fit this". container_loading asks which cargo
        # to load, not how many ships to charter.
        containers = next(
            (
                user_input[k]
                for k in ("containers", "bins", "vessels", "carriers")
                if user_input.get(k)
            ),
            None,
        )
        if containers:
            return self._generate_container_loading(items, containers)

        bin_capacity = user_input.get("bin_capacity", 100)
        max_bins = user_input.get("max_bins", 0)

        if max_bins <= 0:
            max_bins = len(items)

        variables: list[Variable] = []
        constraints: list[Constraint] = []

        # y_j: binary, 1 if bin j is used
        bin_vars: list[str] = []
        for j in range(max_bins):
            y_name = f"bin_{j}"
            variables.append(Variable(name=y_name, type=VariableType.BINARY))
            bin_vars.append(y_name)

        # x_i_j: binary, 1 if item i is in bin j
        for i, item in enumerate(items):
            i_name = self.sanitize_name(item.get("name", f"item_{i}"))
            item_bin_vars: list[str] = []
            for j in range(max_bins):
                var_name = f"{i_name}_in_{j}"
                variables.append(Variable(name=var_name, type=VariableType.BINARY))
                item_bin_vars.append(var_name)

            constraints.append(
                Constraint(
                    name=f"assign_{i_name}",
                    expression=f"{' + '.join(item_bin_vars)} == 1",
                )
            )

        # Capacity constraints
        for j in range(max_bins):
            cap_terms: list[str] = []
            for i, item in enumerate(items):
                i_name = self.sanitize_name(item.get("name", f"item_{i}"))
                # A default of 1 turns the capacity row into a count of items,
                # so a bin holds N crates regardless of how big they are.
                size = self._pick(item, ("size", "volume", "area", "length", "weight"))
                if size is None:
                    raise ValueError(
                        f"Item '{item.get('name', i)}' states no size. "
                        "Expected one of: size, volume, area, length, weight."
                    )
                cap_terms.append(f"{size}*{i_name}_in_{j}")

            constraints.append(
                Constraint(
                    name=f"capacity_{j}",
                    expression=f"{' + '.join(cap_terms)} - {bin_capacity}*bin_{j} <= 0",
                )
            )

        # Symmetry breaking
        for j in range(1, max_bins):
            constraints.append(
                Constraint(
                    name=f"symmetry_{j}",
                    expression=f"bin_{j} - bin_{j - 1} <= 0",
                )
            )

        return OptimizationProblem(
            name="bin_packing",
            description=f"Pack {len(items)} items into bins of capacity {bin_capacity}",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(bin_vars) if bin_vars else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def _generate_container_loading(
        self, items: list[dict[str, Any]], containers: list[dict[str, Any]]
    ) -> OptimizationProblem:
        """Choose what to load into containers that each have their own limits.

        Every item that fits somewhere is worth loading, so the question is
        which cargo to leave behind: maximize the value loaded, and hold every
        container inside each of its stated limits. The plain bin-packing model
        answered a different question entirely — it read no volume, no weight
        and no value (an item's ``size`` defaulted to 1, so its capacity row
        counted crates), and minimized how many containers were used.
        """
        # Only the dimensions BOTH sides state can be enforced.
        active = [
            (item_key, cap_key)
            for item_key, cap_key in self._DIMENSIONS
            if any(i.get(item_key) is not None for i in items)
            and any(c.get(cap_key) is not None for c in containers)
        ]
        if not active:
            raise ValueError(
                "No dimension is stated on both sides. Items carry one of "
                f"{[d[0] for d in self._DIMENSIONS]} and containers the matching "
                f"{[d[1] for d in self._DIMENSIONS]}."
            )

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        value_terms: list[str] = []
        placements: dict[int, list[str]] = {}

        for i, item in enumerate(items):
            i_name = self.sanitize_name(item.get("name", f"item_{i}"))
            value = self._pick(item, self._VALUE_KEYS)
            if value is None:
                raise ValueError(
                    f"Cargo item '{item.get('name', i)}' states no value. "
                    f"Expected one of: {', '.join(self._VALUE_KEYS)}."
                )
            for c, container in enumerate(containers):
                c_name = self.sanitize_name(container.get("name", f"container_{c}"))
                var = f"{i_name}_in_{c_name}"
                variables.append(Variable(name=var, type=VariableType.BINARY))
                placements.setdefault(i, []).append(var)
                value_terms.append(f"{value}*{var}")

            constraints.append(
                Constraint(
                    name=f"once_{i_name}",
                    expression=f"{' + '.join(placements[i])} <= 1",
                )
            )

        # A carrier that costs money to run only earns its keep if what it
        # carries is worth more than sailing it. Without this the fleet is free
        # and every vessel is worth using.
        for c, container in enumerate(containers):
            c_name = self.sanitize_name(container.get("name", f"container_{c}"))
            running = self._pick(container, ("daily_cost", "running_cost", "fixed_cost"))
            if running is None:
                continue
            used = f"used_{c_name}"
            variables.append(Variable(name=used, type=VariableType.BINARY))
            value_terms.append(f"-{running}*{used}")
            for i in range(len(items)):
                constraints.append(
                    Constraint(
                        name=f"uses_{c_name}_{i}",
                        expression=f"{placements[i][c]} - {used} <= 0",
                    )
                )

        for c, container in enumerate(containers):
            c_name = self.sanitize_name(container.get("name", f"container_{c}"))
            for item_key, cap_key in active:
                limit = container.get(cap_key)
                if limit is None:
                    continue
                terms = []
                for i, item in enumerate(items):
                    amount = item.get(item_key)
                    if amount is None:
                        raise ValueError(
                            f"Cargo item '{item.get('name', i)}' states no '{item_key}' "
                            f"while container '{c_name}' limits it."
                        )
                    terms.append(f"{float(amount)}*{placements[i][c]}")
                constraints.append(
                    Constraint(
                        name=f"{item_key}_{c_name}",
                        expression=f"{' + '.join(terms)} <= {float(limit)}",
                    )
                )

        return OptimizationProblem(
            name="container_loading",
            description=(
                f"Load {len(items)} cargo items into {len(containers)} containers, "
                f"respecting {', '.join(k for k, _ in active)}"
            ),
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression=" + ".join(value_terms)),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
