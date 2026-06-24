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

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        items = user_input.get("items", [])
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
                size = item.get("size", 1)
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
