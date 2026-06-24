"""Set cover generator — weighted set cover and minimum dominating set problems."""

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


class SetCoverGenerator(BaseGenerator):
    """Generate weighted set cover problems.

    Given sets with costs and elements they cover, find minimum-cost
    collection of sets that covers all elements.

    Differs from CoveringGenerator: elements are named strings (not indices),
    and sets specify their elements explicitly.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        sets = user_input.get("sets", [])

        # Collect all unique elements
        all_elements: set[str] = set()
        for s in sets:
            all_elements.update(s.get("elements", []))

        variables: list[Variable] = []
        cost_terms: list[str] = []

        for s in sets:
            s_name = self.sanitize_name(s.get("name", f"set_{len(variables)}"))
            cost = s.get("cost", 1)
            variables.append(Variable(name=s_name, type=VariableType.BINARY))
            cost_terms.append(f"{cost}*{s_name}")

        constraints: list[Constraint] = []

        # Each element must be covered by at least one set
        for elem in sorted(all_elements):
            covering_vars: list[str] = []
            for s in sets:
                s_name = self.sanitize_name(s.get("name", ""))
                if elem in s.get("elements", []):
                    covering_vars.append(s_name)

            if covering_vars:
                constraints.append(
                    Constraint(
                        name=f"cover_{self.sanitize_name(elem)}",
                        expression=f"{' + '.join(covering_vars)} >= 1",
                    )
                )

        return OptimizationProblem(
            name="set_cover",
            description=(
                f"Cover {len(all_elements)} elements with minimum cost from {len(sets)} sets"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
