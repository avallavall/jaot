"""Assignment generator — worker-task assignment problems.

Supports domain-specific input formats (equipment-sites, adjusters-claims,
SKUs-slots, etc.) by auto-detecting the two lists.
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


class AssignmentGenerator(BaseGenerator):
    """Generate assignment problems (worker-task, machine-job, etc.).

    Params:
        description: Custom problem description
    """

    def _find_two_lists(self, user_input: dict[str, Any]) -> tuple[list[Any], list[Any]]:
        """Auto-detect the two entity lists (workers/tasks) from input."""
        workers = find_list_field(
            user_input,
            [
                "workers",
                "resources",
                "adjusters",
                "equipment",
                "train_units",
                "skus",
                "agents",
            ],
        )
        tasks = find_list_field(
            user_input,
            [
                "tasks",
                "jobs",
                "sites",
                "claims",
                "services",
                "fires",
                "slots",
                "berths",
            ],
        )

        if workers and tasks:
            return workers, tasks

        # Fallback: pick the two lists from the input
        lists = [(k, v) for k, v in user_input.items() if isinstance(v, list) and v]
        if len(lists) >= 2:
            return lists[0][1], lists[1][1]
        if len(lists) == 1:
            return lists[0][1], lists[0][1]

        return [], []

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        workers, tasks = self._find_two_lists(user_input)
        costs = user_input.get("costs", {})

        variables: list[Variable] = []
        cost_terms: list[str] = []

        for w in workers:
            w_name = self.sanitize_name(w.get("name", w) if isinstance(w, dict) else w)
            for t in tasks:
                t_name = self.sanitize_name(t.get("name", t) if isinstance(t, dict) else t)
                var_name = f"{w_name}_{t_name}"

                variables.append(Variable(name=var_name, type=VariableType.BINARY))

                cost = costs.get(f"{w_name}_{t_name}", 1)
                cost_terms.append(f"{cost}*{var_name}")

        if not variables:
            raise ValueError(
                "Assignment generator requires workers/resources and tasks/jobs. "
                f"Got keys: {list(user_input.keys())}"
            )

        constraints: list[Constraint] = []

        # Each worker assigned to at most one task
        for w in workers:
            w_name = self.sanitize_name(w.get("name", w) if isinstance(w, dict) else w)
            worker_vars = [
                f"{w_name}_{self.sanitize_name(t.get('name', t) if isinstance(t, dict) else t)}"
                for t in tasks
            ]
            constraints.append(
                Constraint(
                    name=f"worker_{w_name}",
                    expression=f"{' + '.join(worker_vars)} <= 1",
                )
            )

        # Each task assigned to exactly one worker
        for t in tasks:
            t_name = self.sanitize_name(t.get("name", t) if isinstance(t, dict) else t)
            task_vars = [
                f"{self.sanitize_name(w.get('name', w) if isinstance(w, dict) else w)}_{t_name}"
                for w in workers
            ]
            constraints.append(
                Constraint(
                    name=f"task_{t_name}",
                    expression=f"{' + '.join(task_vars)} == 1",
                )
            )

        description = params.get(
            "description",
            f"Assign {len(workers)} workers to {len(tasks)} tasks",
        )

        return OptimizationProblem(
            name="assignment",
            description=description,
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
