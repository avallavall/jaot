"""Strip packing generator — 2D rectangular packing in a fixed-width strip.

Positions rectangular items in a strip of fixed width, minimizing the
total strip height (length). Uses big-M non-overlap constraints.
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


class StripPackingGenerator(BaseGenerator):
    """Generate 2D strip packing problems.

    Each item has width and height. The strip has a fixed width.
    Minimize the total height used while placing all items without overlap.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        items = find_list_field(user_input, ["items", "rectangles", "pieces"])
        if not items:
            raise ValueError(
                f"Strip packing requires an items list. Got keys: {list(user_input.keys())}"
            )
        if len(items) > 25:
            raise ValueError(
                f"Strip packing with {len(items)} items generates O(n²) binary variables. "
                f"Reduce to ≤25 items for tractable solve times."
            )

        strip_width = float(user_input.get("strip_width", user_input.get("width", 100)))
        total_height = sum(float(it.get("height", it.get("h", 1))) for it in items)
        big_m_x = strip_width  # tighter M for x-direction constraints
        big_m_y = total_height  # tighter M for y-direction constraints

        variables: list[Variable] = []

        # Position variables (x, y) for each item
        for it in items:
            name = self.sanitize_name(it.get("name", f"item_{len(variables)}"))
            w = float(it.get("width", it.get("w", 1)))
            h = float(it.get("height", it.get("h", 1)))

            variables.append(
                Variable(
                    name=f"x_{name}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=strip_width - w,
                )
            )
            variables.append(
                Variable(
                    name=f"y_{name}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=total_height - h,
                )
            )

        # Strip height variable (to minimize)
        variables.append(
            Variable(
                name="strip_height",
                type=VariableType.CONTINUOUS,
                lower_bound=0,
                upper_bound=total_height,
            )
        )

        constraints: list[Constraint] = []

        # Height bound: y_i + h_i <= strip_height for each item
        for it in items:
            name = self.sanitize_name(it.get("name", ""))
            h = float(it.get("height", it.get("h", 1)))
            constraints.append(
                Constraint(name=f"height_{name}", expression=f"y_{name} + {h} - strip_height <= 0")
            )

        # Non-overlap: for each pair (i, j) with i < j
        # At least one of 4 disjunctions must hold (big-M formulation):
        #   x_i + w_i <= x_j + M*b1  (i left of j)
        #   x_j + w_j <= x_i + M*b2  (j left of i)
        #   y_i + h_i <= y_j + M*b3  (i below j)
        #   y_j + h_j <= y_i + M*b4  (j below i)
        #   b1 + b2 + b3 + b4 <= 3   (at least one constraint active)
        item_names = [self.sanitize_name(it.get("name", f"item_{i}")) for i, it in enumerate(items)]

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ni, nj = item_names[i], item_names[j]
                wi = float(items[i].get("width", items[i].get("w", 1)))
                hi = float(items[i].get("height", items[i].get("h", 1)))
                wj = float(items[j].get("width", items[j].get("w", 1)))
                hj = float(items[j].get("height", items[j].get("h", 1)))

                # 4 binary indicators for the disjunction
                for k in range(4):
                    variables.append(Variable(name=f"b_{ni}_{nj}_{k}", type=VariableType.BINARY))

                # i left of j: x_i + wi - x_j <= M * b_0
                constraints.append(
                    Constraint(
                        name=f"left_{ni}_{nj}",
                        expression=f"x_{ni} + {wi} - x_{nj} - {big_m_x}*b_{ni}_{nj}_0 <= 0",
                    )
                )
                # j left of i: x_j + wj - x_i <= M * b_1
                constraints.append(
                    Constraint(
                        name=f"right_{ni}_{nj}",
                        expression=f"x_{nj} + {wj} - x_{ni} - {big_m_x}*b_{ni}_{nj}_1 <= 0",
                    )
                )
                # i below j: y_i + hi - y_j <= M * b_2
                constraints.append(
                    Constraint(
                        name=f"below_{ni}_{nj}",
                        expression=f"y_{ni} + {hi} - y_{nj} - {big_m_y}*b_{ni}_{nj}_2 <= 0",
                    )
                )
                # j below i: y_j + hj - y_i <= M * b_3
                constraints.append(
                    Constraint(
                        name=f"above_{ni}_{nj}",
                        expression=f"y_{nj} + {hj} - y_{ni} - {big_m_y}*b_{ni}_{nj}_3 <= 0",
                    )
                )
                # At least one must be active
                constraints.append(
                    Constraint(
                        name=f"disjunct_{ni}_{nj}",
                        expression=f"b_{ni}_{nj}_0 + b_{ni}_{nj}_1 + b_{ni}_{nj}_2 + b_{ni}_{nj}_3 <= 3",
                    )
                )

        return OptimizationProblem(
            name="strip_packing",
            description=f"Pack {len(items)} items in strip of width {strip_width}",
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="strip_height"),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=120),
        )
