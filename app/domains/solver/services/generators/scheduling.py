"""Scheduling generator — employee/resource scheduling problems.

Supports domain-specific input formats by auto-detecting lists of
workers/resources and shifts/tasks/jobs from the input dict.
"""

from typing import Any

from app.domains.solver.services.generators.base import (
    BaseGenerator,
    find_list_field,
    find_scalar_field,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class SchedulingGenerator(BaseGenerator):
    """Generate employee/resource scheduling problems.

    Params:
        objective: "minimize_cost" (default) or "minimize_shifts"
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        # No generic fallback here: shifts/tasks detection below also falls back
        # to "the first list in the input", so a single-list input (stands,
        # blocks, trial phases…) would hand the SAME list to both roles and the
        # model became an X-assigned-to-X assignment answering nothing. Those
        # single-list inputs are exactly what task scheduling below is for.
        employees = find_list_field(
            user_input,
            [
                "employees",
                "workers",
                "resources",
                "satellites",
                "trains",
                "vessels",
                "crews",
                "machines",
                "num_crews",
            ],
            fallback=False,
        )
        shifts = find_list_field(
            user_input,
            [
                "shifts",
                "tasks",
                "jobs",
                "orders",
                "shipments",
                "berths",
                "activities",
                "sections",
                "maintenance_windows",
                "flight_legs",
                "stands",
                "blocks",
                "lines",
                "trial_phases",
                "sites",
                "track_segments",
                "services",
            ],
        )

        # If only one list found, try harder to build a schedule
        # Some templates provide only tasks/items and build workers implicitly
        if not employees and not shifts:
            raise ValueError(
                "Scheduling generator requires at least workers and shifts/tasks. "
                f"Got keys: {list(user_input.keys())}"
            )

        # Fallback: if no employees found, create implicit resources
        if not employees and shifts:
            # Use integer variables for task-to-period assignments
            return self._generate_task_scheduling(user_input, shifts, params)

        if employees and not shifts:
            raise ValueError("Scheduling generator found employees but no shifts/tasks.")

        objective_type = params.get("objective", user_input.get("objective", "minimize_cost"))
        return self._generate_employee_scheduling(employees, shifts, objective_type)

    def _generate_employee_scheduling(
        self,
        employees: list[dict[str, Any]],
        shifts: list[dict[str, Any]],
        objective_type: str,
    ) -> OptimizationProblem:
        """Classic employee-shift assignment formulation."""
        variables: list[Variable] = []
        cost_terms: list[str] = []
        shift_count_terms: list[str] = []

        for emp in employees:
            e_name = self.sanitize_name(emp.get("name", f"emp_{len(variables)}"))
            hourly_cost = emp.get("hourly_cost", emp.get("cost", 20))
            unavailable = [self.sanitize_name(s) for s in emp.get("unavailable_shifts", [])]

            for shift in shifts:
                s_name = self.sanitize_name(shift.get("name", f"shift_{len(variables)}"))
                var_name = f"{e_name}_{s_name}"
                duration = shift.get("duration_hours", shift.get("duration", 8))

                if s_name in unavailable:
                    variables.append(
                        Variable(
                            name=var_name,
                            type=VariableType.BINARY,
                            lower_bound=0,
                            upper_bound=0,
                        )
                    )
                else:
                    variables.append(Variable(name=var_name, type=VariableType.BINARY))

                cost_terms.append(f"{hourly_cost * duration}*{var_name}")
                shift_count_terms.append(var_name)

        constraints: list[Constraint] = []

        # Coverage constraints
        for shift in shifts:
            s_name = self.sanitize_name(shift.get("name", ""))
            min_emp = shift.get("min_employees", 1)
            max_emp = shift.get("max_employees")

            shift_vars = []
            for emp in employees:
                e_name = self.sanitize_name(emp.get("name", ""))
                shift_vars.append(f"{e_name}_{s_name}")

            expr = " + ".join(shift_vars)
            constraints.append(
                Constraint(
                    name=f"min_cover_{s_name}",
                    expression=f"{expr} >= {min_emp}",
                )
            )
            if max_emp is not None:
                constraints.append(
                    Constraint(
                        name=f"max_cover_{s_name}",
                        expression=f"{expr} <= {max_emp}",
                    )
                )

        # Hours constraints per employee
        for emp in employees:
            e_name = self.sanitize_name(emp.get("name", ""))
            max_hours = emp.get("max_hours", 40)
            min_hours = emp.get("min_hours", 0)

            hour_terms = []
            for shift in shifts:
                s_name = self.sanitize_name(shift.get("name", ""))
                duration = shift.get("duration_hours", shift.get("duration", 8))
                hour_terms.append(f"{duration}*{e_name}_{s_name}")

            hours_expr = " + ".join(hour_terms)
            constraints.append(
                Constraint(
                    name=f"max_hours_{e_name}",
                    expression=f"{hours_expr} <= {max_hours}",
                )
            )
            if min_hours > 0:
                constraints.append(
                    Constraint(
                        name=f"min_hours_{e_name}",
                        expression=f"{hours_expr} >= {min_hours}",
                    )
                )

        if objective_type == "minimize_shifts":
            obj_expr = " + ".join(shift_count_terms) if shift_count_terms else "0"
        else:
            obj_expr = " + ".join(cost_terms) if cost_terms else "0"

        return OptimizationProblem(
            name="employee_scheduling",
            description=f"Schedule {len(employees)} employees across {len(shifts)} shifts",
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression=obj_expr),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def _generate_task_scheduling(
        self,
        user_input: dict[str, Any],
        tasks: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> OptimizationProblem:
        """Task/project scheduling: start times minimizing makespan, honestly.

        Time-indexed: a binary z per (task, admissible start) carries the real
        commitments — precedence declared on the tasks, and at most
        ``num_crews``/``num_resources`` tasks ACTIVE in any period. The previous
        version wrote none of that: its only resource row was a fabricated
        "sum of starts >= n(n-1)/2r", which enforces no capacity and cuts off
        legitimately optimal schedules — so every card served here answered
        "everything starts at once".
        """
        time_horizon = int(
            find_scalar_field(user_input, ["time_horizon", "num_periods", "horizon"], default=20)
        )
        num_resources = int(
            find_scalar_field(user_input, ["num_crews", "num_resources"], default=0)
        )

        names: list[str] = []
        durations: list[int] = []
        for i, task in enumerate(tasks):
            names.append(self.sanitize_name(task.get("name", f"task_{i}")))
            durations.append(
                max(1, int(task.get("duration", task.get("duration_days", task.get("period", 1)))))
            )

        variables: list[Variable] = []
        constraints: list[Constraint] = []

        # z_{i,t}: task i starts at period t. start_i derives from them, so the
        # published solution keeps the start_/makespan surface it always had.
        starts_of: dict[str, list[tuple[int, str]]] = {}
        for t_name, duration in zip(names, durations, strict=True):
            latest = max(0, time_horizon - duration)
            z_names: list[tuple[int, str]] = []
            for t in range(latest + 1):
                z = f"z_{t_name}_{t}"
                variables.append(Variable(name=z, type=VariableType.BINARY))
                z_names.append((t, z))
            starts_of[t_name] = z_names

            variables.append(
                Variable(
                    name=f"start_{t_name}",
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=latest,
                )
            )
            constraints.append(
                Constraint(
                    name=f"one_start_{t_name}",
                    expression=f"{' + '.join(z for _, z in z_names)} == 1",
                )
            )
            start_terms = " + ".join(f"{t}*{z}" for t, z in z_names if t > 0)
            constraints.append(
                Constraint(
                    name=f"start_def_{t_name}",
                    expression=f"start_{t_name} - ({start_terms}) == 0"
                    if start_terms
                    else f"start_{t_name} == 0",
                )
            )

        # Makespan
        variables.append(
            Variable(
                name="makespan",
                type=VariableType.INTEGER,
                lower_bound=0,
                upper_bound=time_horizon,
            )
        )
        for t_name, duration in zip(names, durations, strict=True):
            constraints.append(
                Constraint(
                    name=f"makespan_{t_name}",
                    expression=f"makespan - start_{t_name} >= {duration}",
                )
            )

        # Precedence declared on the tasks themselves (renovation cards list
        # prerequisites; nothing read them before).
        name_by_raw = {str(task.get("name", f"task_{i}")): names[i] for i, task in enumerate(tasks)}
        for i, task in enumerate(tasks):
            prereqs = task.get(
                "prerequisites", task.get("depends_on", task.get("dependencies", []))
            )
            if not isinstance(prereqs, list):
                continue
            for prereq in prereqs:
                p_name = name_by_raw.get(str(prereq), self.sanitize_name(str(prereq)))
                if p_name not in starts_of or p_name == names[i]:
                    continue
                p_duration = durations[names.index(p_name)]
                constraints.append(
                    Constraint(
                        name=f"prec_{p_name}_{names[i]}",
                        expression=f"start_{names[i]} - start_{p_name} >= {p_duration}",
                    )
                )

        # Real concurrency: at most num_crews tasks active in any period. Active
        # at t = started within the last duration periods.
        if 0 < num_resources < len(tasks):
            for t in range(time_horizon):
                active_terms: list[str] = []
                for t_name, duration in zip(names, durations, strict=True):
                    active_terms.extend(
                        z for tau, z in starts_of[t_name] if tau <= t < tau + duration
                    )
                if len(active_terms) > num_resources:
                    constraints.append(
                        Constraint(
                            name=f"crews_{t}",
                            expression=f"{' + '.join(active_terms)} <= {num_resources}",
                        )
                    )

        return OptimizationProblem(
            name="task_scheduling",
            description=f"Schedule {len(tasks)} tasks in {time_horizon} periods",
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="makespan"),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
