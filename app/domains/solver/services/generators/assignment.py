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

#: Rules that become a "<count> <op> 1" row. Shared by the worker and task side.
_OPERATOR = {"exactly_one": "==", "at_most_one": "<="}


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

    @staticmethod
    def _pair_cost(worker: dict[str, Any], task: dict[str, Any], rules: list[Any]) -> float:
        """Cost of one pair, summed from the rules the template declares.

        A card whose cost lives in the two rows rather than in a lookup table
        says how to combine them, instead of the generator guessing. Every rule
        reads a real field, so a changed number changes the model.
        """
        total = 0.0
        for rule in rules:
            if not isinstance(rule, dict) or len(rule) != 1:
                raise ValueError(f"Each cost rule needs exactly one key, got: {rule!r}")
            kind, arg = next(iter(rule.items()))
            if kind == "multiply":
                w_field, t_field = arg
                total += float(worker.get(w_field, 0)) * float(task.get(t_field, 0))
            elif kind == "worker":
                total += float(worker.get(arg, 0))
            elif kind == "task":
                total += float(task.get(arg, 0))
            elif kind == "penalty":
                w_field, t_field = arg["unequal"]
                if worker.get(w_field) != task.get(t_field):
                    # "times" scales the penalty by a task field, so a mismatch
                    # on an urgent job costs more than on a routine one.
                    scale = float(task.get(arg["times"], 0)) if "times" in arg else 1.0
                    total += float(arg["amount"]) * scale
            else:
                raise ValueError(f"Unknown assignment cost rule: {kind!r}")
        return total

    @staticmethod
    def _rule_field(row: dict[str, Any], field: str, side: str, kind: str) -> Any:
        """Read a compatibility field, refusing to guess when it is absent.

        A missing field used to read as 0 (or as an empty allow-list), so a
        rule the card declares stopped constraining the moment the user's
        column was named differently. A 40 kg pallet then went into a slot
        rated for 30 kg, and the solve reported optimal.
        """
        if field not in row or row[field] is None:
            raise ValueError(
                f"Compatibility rule '{kind}' reads '{field}' on the {side} row "
                f"'{row.get('name', '?')}', which does not carry it. "
                f"Fields present: {sorted(row)}."
            )
        return row[field]

    @staticmethod
    def _pair_allowed(worker: dict[str, Any], task: dict[str, Any], rules: list[Any]) -> bool:
        """Whether this worker may take this task at all."""
        read = AssignmentGenerator._rule_field
        for rule in rules:
            if not isinstance(rule, dict) or len(rule) != 1:
                raise ValueError(f"Each compatibility rule needs exactly one key, got: {rule!r}")
            kind, arg = next(iter(rule.items()))
            w_field, t_field = arg
            if kind == "equal":
                if read(worker, w_field, "worker", kind) != read(task, t_field, "task", kind):
                    return False
            elif kind == "member":
                allowed = read(worker, w_field, "worker", kind)
                if read(task, t_field, "task", kind) not in allowed:
                    return False
            elif kind == "at_least":
                if float(read(worker, w_field, "worker", kind)) < float(
                    read(task, t_field, "task", kind)
                ):
                    return False
            elif kind == "at_most":
                # The limit sits on the task side: a 40 kg pallet needs a slot
                # rated for it, so worker[field] must not exceed task[field].
                if float(read(worker, w_field, "worker", kind)) > float(
                    read(task, t_field, "task", kind)
                ):
                    return False
            else:
                raise ValueError(f"Unknown assignment compatibility rule: {kind!r}")
        return True

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        workers, tasks = self._find_two_lists(user_input)

        # Cost keys are written by the user and keep their original case
        # ("roomA_slot1"); variable names are sanitized and lowercased. Looking
        # up the raw key missed every capitalised pair and fell back to a cost
        # of 1, which made the objective a constant and any feasible
        # assignment "optimal". Key the table the same way the variables are.
        raw_costs = user_input.get("costs") or {}
        costs = {self.sanitize_name(k): v for k, v in raw_costs.items()}

        cost_rules = params.get("cost") or []
        require = params.get("require") or []
        worker_rule = params.get("worker_rule", "at_most_one")
        task_rule = params.get("task_rule", "exactly_one")
        capacity_field = params.get("capacity_field")
        needs_field = params.get("needs_field", "needs")
        type_field = params.get("type_field", "type")
        idle_cost_field = params.get("idle_cost_field")
        demand_field = params.get("demand_field", "demand")
        supply_field = params.get("supply_field", "supply")

        # Without a cost table and without cost rules every pair used to cost
        # 1, so the objective counted assignments instead of pricing them.
        if not raw_costs and not cost_rules:
            raise ValueError(
                "Assignment needs a cost: either a 'costs' table keyed by "
                "'<worker>_<task>', or cost rules in generator_params."
            )

        # Pair variables are "<worker>_<task>", so two workers or two tasks that
        # sanitize alike write to the same variable and one of them is quietly
        # dropped from the plan.
        for rows, label in ((workers, "Workers"), (tasks, "Tasks")):
            raw = [(r if isinstance(r, dict) else {"name": r}).get("name", r) for r in rows]
            self.reject_name_collisions([self.sanitize_name(n) for n in raw], raw, label)

        # Check the worker rule before a single row is built. The idle-cost
        # branch below skips the rest of the worker loop, so on any card that
        # sets an idle cost the "Unknown worker_rule" check was unreachable:
        # a typo, or a capacity rule with a missing field, rendered a model
        # byte-identical to the correct one and reported optimal.
        if worker_rule != "capacity" and worker_rule not in _OPERATOR:
            raise ValueError(f"Unknown worker_rule: {worker_rule!r}")
        if worker_rule == "capacity":
            if not capacity_field:
                raise ValueError("worker_rule 'capacity' needs a capacity_field.")
            if idle_cost_field:
                raise ValueError(
                    "worker_rule 'capacity' cannot be combined with idle_cost_field: "
                    "the idle row already pins each worker at one task or idle."
                )

        variables: list[Variable] = []
        cost_terms: list[str] = []
        missing: list[str] = []
        # pairs[w_name] = [(t_name, var_name), …] for the pairs that are allowed
        pairs_by_worker: dict[str, list[str]] = {}
        pairs_by_task: dict[str, list[str]] = {}

        for w in workers:
            w_row = w if isinstance(w, dict) else {"name": w}
            w_name = self.sanitize_name(w_row.get("name", w))
            for t in tasks:
                t_row = t if isinstance(t, dict) else {"name": t}
                t_name = self.sanitize_name(t_row.get("name", t))
                if not self._pair_allowed(w_row, t_row, require):
                    continue
                var_name = f"{w_name}_{t_name}"

                variables.append(Variable(name=var_name, type=VariableType.BINARY))
                pairs_by_worker.setdefault(w_name, []).append(var_name)
                pairs_by_task.setdefault(t_name, []).append(var_name)

                if cost_rules:
                    cost: float | Any = self._pair_cost(w_row, t_row, cost_rules)
                else:
                    if var_name not in costs:
                        missing.append(var_name)
                    cost = costs.get(var_name, 1)
                cost_terms.append(f"{cost}*{var_name}")

        # A cost table that does not cover every pair is a data error. Saying so
        # beats silently costing the uncovered pairs at 1.
        if missing:
            shown = ", ".join(missing[:5])
            raise ValueError(
                f"Assignment costs cover {len(costs)} of {len(variables)} worker-task pairs. "
                f"Missing: {shown}{'…' if len(missing) > 5 else ''}"
            )

        if not variables:
            raise ValueError(
                "Assignment generator requires workers/resources and tasks/jobs. "
                f"Got keys: {list(user_input.keys())}"
            )

        constraints: list[Constraint] = []

        # How many tasks one worker may hold. "capacity" reads a per-worker
        # limit from the data: an adjuster with max_cases 3 takes three claims,
        # which "at most one" could never express.
        for w in workers:
            w_row = w if isinstance(w, dict) else {"name": w}
            w_name = self.sanitize_name(w_row.get("name", w))
            worker_vars = pairs_by_worker.get(w_name)
            if not worker_vars:
                continue
            if idle_cost_field:
                # Idle cost is what a machine costs when it is NOT working, so
                # it hangs off a binary that is 1 exactly when nothing is
                # assigned. Charging it on the assigned pairs instead would
                # price the fleet backwards and park the dearest machine.
                idle = f"idle_{w_name}"
                rate = w_row.get(idle_cost_field)
                if rate is None:
                    raise ValueError(
                        f"Worker '{w_row.get('name', w_name)}' has no '{idle_cost_field}'."
                    )
                variables.append(Variable(name=idle, type=VariableType.BINARY))
                cost_terms.append(f"{float(rate)}*{idle}")
                constraints.append(
                    Constraint(
                        name=f"idle_{w_name}",
                        expression=f"{' + '.join(worker_vars)} + {idle} == 1",
                    )
                )
                continue
            if worker_rule == "capacity":
                if not capacity_field:
                    raise ValueError("worker_rule 'capacity' needs a capacity_field.")
                limit = w_row.get(capacity_field)
                if limit is None:
                    raise ValueError(
                        f"Worker '{w_row.get('name', w_name)}' has no '{capacity_field}'."
                    )
                expression = f"{' + '.join(worker_vars)} <= {float(limit)}"
            elif worker_rule in _OPERATOR:
                expression = f"{' + '.join(worker_vars)} {_OPERATOR[worker_rule]} 1"
            else:
                raise ValueError(f"Unknown worker_rule: {worker_rule!r}")
            constraints.append(Constraint(name=f"worker_{w_name}", expression=expression))

        for t in tasks:
            t_row = t if isinstance(t, dict) else {"name": t}
            t_name = self.sanitize_name(t_row.get("name", t))
            task_vars = pairs_by_task.get(t_name)
            if not task_vars:
                # Only reachable when compatibility rules rule out every
                # worker, which makes an "exactly one" model infeasible with
                # no explanation. Name the task instead.
                if task_rule == "exactly_one":
                    raise ValueError(
                        f"No worker is compatible with '{t_row.get('name', t_name)}', "
                        "so it can never be assigned."
                    )
                continue
            if task_rule == "demand_sum":
                # Some jobs take as many workers as it takes: a wildfire needs
                # enough suppression effectiveness on it, not one crew.
                need = t_row.get(demand_field)
                if need is None:
                    raise ValueError(
                        f"'{t_row.get('name', t_name)}' has no '{demand_field}' to cover."
                    )
                terms = []
                for w in workers:
                    if not isinstance(w, dict):
                        continue
                    var = f"{self.sanitize_name(w.get('name', ''))}_{t_name}"
                    if var not in task_vars:
                        continue
                    supply = w.get(supply_field)
                    if supply is None:
                        raise ValueError(
                            f"Worker '{w.get('name', '')}' has no '{supply_field}' to contribute."
                        )
                    terms.append(f"{float(supply)}*{var}")
                constraints.append(
                    Constraint(
                        name=f"cover_{t_name}",
                        expression=f"{' + '.join(terms)} >= {float(need)}",
                    )
                )
                continue
            if task_rule == "demand_by_type":
                # A construction site does not need "one machine", it needs one
                # excavator and one crane. Write a row per type it asks for.
                # No "or {}" here: the studio's Add-row button writes "" into an
                # object column, and an empty string is falsy. The row then got
                # its variables and its objective terms but no demand row at
                # all, so nothing required anything of it and the solve was
                # optimal with that site served by nobody.
                needs = t_row.get(needs_field)
                if not isinstance(needs, dict):
                    raise ValueError(
                        f"'{t_row.get('name', t_name)}' needs a '{needs_field}' map of "
                        f"type -> count, got {needs!r}."
                    )
                for kind, count in needs.items():
                    of_kind = [
                        f"{self.sanitize_name(w.get('name', ''))}_{t_name}"
                        for w in workers
                        if isinstance(w, dict) and w.get(type_field) == kind
                    ]
                    of_kind = [v for v in of_kind if v in task_vars]
                    if not of_kind and float(count) > 0:
                        raise ValueError(
                            f"'{t_row.get('name', t_name)}' asks for {count} of type "
                            f"'{kind}' and no worker has that type."
                        )
                    if of_kind:
                        constraints.append(
                            Constraint(
                                name=f"need_{t_name}_{self.sanitize_name(kind)}",
                                expression=f"{' + '.join(of_kind)} == {float(count)}",
                            )
                        )
                continue
            if task_rule not in _OPERATOR:
                raise ValueError(f"Unknown task_rule: {task_rule!r}")
            constraints.append(
                Constraint(
                    name=f"task_{t_name}",
                    expression=f"{' + '.join(task_vars)} {_OPERATOR[task_rule]} 1",
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
