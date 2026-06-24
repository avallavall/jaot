"""Quality control sampling generator — inspection plan optimization.

Determines how many samples to inspect from each production batch
to minimize total inspection cost while meeting a target defect
detection rate within a budget.
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


class QualityControlGenerator(BaseGenerator):
    """Generate quality control sampling problems."""

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        batches = find_list_field(user_input, ["batches", "production_lines", "lots", "products"])
        if not batches:
            raise ValueError(
                f"Quality control requires a batches list. Got keys: {list(user_input.keys())}"
            )

        budget = float(user_input.get("inspection_budget", user_input.get("budget", 0)))
        min_detection_rate = float(
            user_input.get("min_detection_rate", user_input.get("target_detection", 0))
        )
        total_defects_estimate = float(user_input.get("total_defects_estimate", 0))

        variables: list[Variable] = []
        cost_terms: list[str] = []
        detection_terms: list[str] = []

        for batch in batches:
            name = self.sanitize_name(batch.get("name", f"batch_{len(variables)}"))
            batch_size = int(batch.get("batch_size", batch.get("size", 100)))
            cost_per_sample = float(batch.get("cost_per_sample", batch.get("inspection_cost", 1)))
            defect_rate = float(batch.get("defect_rate", batch.get("expected_defect_rate", 0.01)))

            variables.append(
                Variable(
                    name=name, type=VariableType.INTEGER, lower_bound=0, upper_bound=batch_size
                )
            )
            cost_terms.append(f"{cost_per_sample}*{name}")
            if defect_rate > 0:
                detection_terms.append(f"{defect_rate}*{name}")

        constraints: list[Constraint] = []

        # Budget constraint
        if budget > 0:
            constraints.append(
                Constraint(name="budget", expression=f"{' + '.join(cost_terms)} <= {budget}")
            )

        # Minimum detection: SUM(defect_rate_i * samples_i) >= min_detection_rate * total_defects
        if min_detection_rate > 0 and detection_terms:
            rhs = (
                min_detection_rate * total_defects_estimate
                if total_defects_estimate > 0
                else min_detection_rate
            )
            constraints.append(
                Constraint(
                    name="min_detection",
                    expression=f"{' + '.join(detection_terms)} >= {rhs}",
                )
            )

        return OptimizationProblem(
            name="quality_control_sampling",
            description=f"Optimize sampling plan across {len(batches)} batches",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
