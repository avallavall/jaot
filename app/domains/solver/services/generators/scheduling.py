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
        """Task/project scheduling: assign start times to tasks, minimize makespan."""
        time_horizon = int(
            find_scalar_field(user_input, ["time_horizon", "num_periods", "horizon"], default=20)
        )
        num_resources = int(
            find_scalar_field(user_input, ["num_crews", "num_resources"], default=2)
        )
        capacity = int(
            find_scalar_field(
                user_input,
                ["plant_capacity", "capacity", "max_area_per_period"],
                default=len(tasks),
            )
        )

        variables: list[Variable] = []
        constraints: list[Constraint] = []

        # Start-time variables for each task (integer)
        for i, task in enumerate(tasks):
            t_name = self.sanitize_name(task.get("name", f"task_{i}"))
            duration = task.get("duration", task.get("duration_days", task.get("period", 1)))

            variables.append(
                Variable(
                    name=f"start_{t_name}",
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=max(0, time_horizon - duration),
                )
            )

        # Makespan variable
        variables.append(
            Variable(
                name="makespan",
                type=VariableType.INTEGER,
                lower_bound=0,
                upper_bound=time_horizon,
            )
        )

        # Makespan >= start_i + duration_i for all tasks
        for i, task in enumerate(tasks):
            t_name = self.sanitize_name(task.get("name", f"task_{i}"))
            duration = task.get("duration", task.get("duration_days", task.get("period", 1)))
            constraints.append(
                Constraint(
                    name=f"makespan_{t_name}",
                    expression=f"makespan - start_{t_name} >= {duration}",
                )
            )

        # Resource constraint: at most 'capacity' tasks active in each period
        # Simplified as sum-of-all-starts constraint for tractability
        if capacity < len(tasks):
            all_starts = " + ".join(
                f"start_{self.sanitize_name(task.get('name', f'task_{i}'))}"
                for i, task in enumerate(tasks)
            )
            # Encourage spread: sum of starts >= some minimum
            min_spread = len(tasks) * (len(tasks) - 1) // (2 * max(1, num_resources))
            constraints.append(
                Constraint(
                    name="resource_spread",
                    expression=f"{all_starts} >= {min_spread}",
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
