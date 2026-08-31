"""Windowed tasking generator — time-indexed scheduling on parallel resources.

Two cards share one shape: work that must happen inside a time window, on a
resource that can only handle one job at a time.

- ``select`` mode (default): the work is optional and competes for scarce
  resource time. Satellite observations, each with a visibility window, a
  duration and a priority, against per-satellite minute budgets. Maximize the
  priority actually collected.
- ``serve_all`` mode (``generator_params: {mode: serve_all}``): every job must
  be served, and the cost is how long it waits after it becomes available.
  Vessels arriving at a port, each needing a berth deep enough for its draft.
  Minimize total waiting.

Both used to reach the scheduling generator, which builds a worker-shift
assignment: it read neither the windows nor the durations nor the priorities,
forced every job to be covered, and minimized a cost that was not in the input.
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

#: A time-indexed model grows as jobs x resources x horizon. Past this many
#: start variables the formulation stops being the right tool, and saying so
#: beats handing the solver a model it will time out on.
_MAX_START_VARS = 40_000


class WindowedTaskingGenerator(BaseGenerator):
    """Schedule jobs into time windows on resources that serve one at a time."""

    _JOB_KEYS = ["tasks", "jobs", "orders", "vessels", "observations", "requests", "items"]
    _RESOURCE_KEYS = [
        "satellites",
        "berths",
        "machines",
        "lines",
        "resources",
        "servers",
        "stations",
    ]

    _DURATION_KEYS = (
        "duration",
        "handling_hours",
        "duration_minutes",
        "processing_hours",
        "production_hours",
    )
    _RELEASE_KEYS = ("window_start", "arrival_hour", "earliest_start", "release")
    _DEADLINE_KEYS = ("window_end", "latest_finish", "deadline_hour", "deadline")
    _VALUE_KEYS = ("priority", "value", "revenue", "weight")

    #: A job attribute that a resource caps. Port draft is the live case: a
    #: 15 m vessel cannot use a 14 m berth.
    _FIT_PAIRS = (
        ("draft_m", "max_draft_m"),
        ("volume_kg", "capacity_kg"),
        ("batch_kg", "capacity_kg"),
        ("length_m", "max_length_m"),
        ("weight_t", "max_weight_t"),
        ("size", "max_size"),
    )

    _CAPACITY_KEYS = ("capacity_minutes", "capacity_hours", "available_hours", "capacity")

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        jobs = find_list_field(user_input, self._JOB_KEYS, fallback=False)
        resources = find_list_field(user_input, self._RESOURCE_KEYS, fallback=False)
        if not jobs:
            raise ValueError(
                "Windowed tasking requires a list of jobs to schedule "
                f"({', '.join(self._JOB_KEYS)}). Got keys: {list(user_input.keys())}"
            )
        if not resources:
            raise ValueError(
                "Windowed tasking requires a list of resources to schedule onto "
                f"({', '.join(self._RESOURCE_KEYS)}). Got keys: {list(user_input.keys())}"
            )

        serve_all = params.get("mode") == "serve_all"

        durations: list[int] = []
        for i, job in enumerate(jobs):
            duration = self.first_number(job, self._DURATION_KEYS)
            if duration is None or duration <= 0:
                raise ValueError(
                    f"Job '{job.get('name', i)}' has no positive duration. "
                    f"Expected one of: {', '.join(self._DURATION_KEYS)}."
                )
            durations.append(max(1, int(round(duration))))

        # The horizon has to hold the work. Without a stated one, allow every
        # job to run back to back on a single resource.
        stated = self.first_number(user_input, ("time_horizon", "horizon", "planning_hours"))
        latest_deadline = max((self.first_number(job, self._DEADLINE_KEYS) or 0) for job in jobs)
        horizon = int(stated or max(latest_deadline, sum(durations)))
        if horizon <= 0:
            raise ValueError("Windowed tasking needs a positive time horizon.")

        job_names = [self.sanitize_name(j.get("name", f"job_{i}")) for i, j in enumerate(jobs)]
        res_names = [self.sanitize_name(r.get("name", f"res_{i}")) for i, r in enumerate(resources)]

        # starts[i][r] = [(t, var_name), …] for every start this job can take
        # on that resource: inside its window, finishing before its deadline,
        # and only where the job physically fits.
        # Two passes. The first only counts, because the cap used to be checked
        # after every Variable had already been built: an oversized card paid
        # the whole build before being told no, inside the request handler.
        windows: list[dict[int, tuple[int, int]]] = []
        blocked: list[str] = []
        projected = 0
        for i, job in enumerate(jobs):
            release = int(self.first_number(job, self._RELEASE_KEYS) or 0)
            deadline = int(self.first_number(job, self._DEADLINE_KEYS) or horizon)
            latest = min(deadline, horizon) - durations[i]
            per_resource: dict[int, tuple[int, int]] = {}
            for r, resource in enumerate(resources):
                if not self._fits(job, resource) or latest < release:
                    continue
                per_resource[r] = (release, latest)
                projected += latest - release + 1
            if not per_resource:
                blocked.append(
                    f"{job.get('name', i)} (needs {durations[i]} between {release} and {deadline})"
                )
            windows.append(per_resource)

        if projected > _MAX_START_VARS:
            raise ValueError(
                f"Windowed tasking would need {projected:,} start variables "
                f"(limit {_MAX_START_VARS:,}). Shorten the horizon or the windows."
            )

        starts: list[dict[int, list[tuple[int, str]]]] = []
        variables: list[Variable] = []
        for i in range(len(jobs)):
            per_resource_slots: dict[int, list[tuple[int, str]]] = {}
            for r, (release, latest) in windows[i].items():
                slots = [
                    (t, f"z_{job_names[i]}_{res_names[r]}_{t}") for t in range(release, latest + 1)
                ]
                per_resource_slots[r] = slots
                variables.extend(
                    Variable(name=name, type=VariableType.BINARY) for _t, name in slots
                )
            starts.append(per_resource_slots)

        # A job that fits nowhere makes serve_all impossible, so say so. In
        # select mode the work is optional by construction: a candidate that
        # does not fit is simply one the plan cannot pick, and raising there
        # turned a working card into a hard failure the moment a user added
        # one row with a window shorter than its own duration.
        if blocked and serve_all:
            raise ValueError(
                f"{len(blocked)} job(s) cannot be scheduled anywhere: {'; '.join(blocked[:5])}"
            )

        constraints: list[Constraint] = []

        # One start per job — exactly one when every job must be served. A job
        # with no feasible start has no terms, and an empty left-hand side is
        # not an expression; in select mode such a job is simply never picked.
        for i, name in enumerate(job_names):
            all_slots = [var for slots in starts[i].values() for _t, var in slots]
            if not all_slots:
                continue
            constraints.append(
                Constraint(
                    name=f"once_{name}",
                    expression=f"{' + '.join(all_slots)} {'==' if serve_all else '<='} 1",
                )
            )

        # A resource serves one job at a time: at every instant, at most one
        # job is running on it.
        for r, res_name in enumerate(res_names):
            for t in range(horizon):
                busy = [
                    var
                    for i in range(len(jobs))
                    for tau, var in starts[i].get(r, [])
                    if tau <= t < tau + durations[i]
                ]
                if len(busy) > 1:
                    constraints.append(
                        Constraint(
                            name=f"busy_{res_name}_{t}",
                            expression=f"{' + '.join(busy)} <= 1",
                        )
                    )

        # Total working time booked on a resource, when it has a budget.
        for r, resource in enumerate(resources):
            budget = self.first_number(resource, self._CAPACITY_KEYS)
            if budget is None:
                continue
            terms = [
                f"{durations[i]}*{var}"
                for i in range(len(jobs))
                for _t, var in starts[i].get(r, [])
            ]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"budget_{res_names[r]}",
                        expression=f"{' + '.join(terms)} <= {budget}",
                    )
                )

        # A readable start time per job, so the answer names when work begins.
        for i, name in enumerate(job_names):
            variables.append(
                Variable(
                    name=f"start_{name}",
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=horizon,
                )
            )
            weighted = " + ".join(
                f"{t}*{var}" for slots in starts[i].values() for t, var in slots if t > 0
            )
            constraints.append(
                Constraint(
                    name=f"start_def_{name}",
                    expression=f"start_{name} - ({weighted}) == 0"
                    if weighted
                    else f"start_{name} == 0",
                )
            )

        if serve_all:
            # Waiting is the gap between becoming available and starting.
            wait_terms = [
                f"{t - int(self.first_number(jobs[i], self._RELEASE_KEYS) or 0)}*{var}"
                for i in range(len(jobs))
                for slots in starts[i].values()
                for t, var in slots
                if t > int(self.first_number(jobs[i], self._RELEASE_KEYS) or 0)
            ]
            return OptimizationProblem(
                name="windowed_serve_all",
                description=(
                    f"Serve {len(jobs)} jobs on {len(resources)} resources with the least waiting"
                ),
                variables=variables,
                objective=Objective(
                    sense=ObjectiveSense.MINIMIZE,
                    expression=" + ".join(wait_terms) if wait_terms else "0",
                ),
                constraints=constraints,
                options=SolverOptions(time_limit_seconds=60),
            )

        value_terms = [
            f"{self.first_number(jobs[i], self._VALUE_KEYS) or 1}*{var}"
            for i in range(len(jobs))
            for slots in starts[i].values()
            for _t, var in slots
        ]
        return OptimizationProblem(
            name="windowed_selection",
            description=(f"Choose which of {len(jobs)} jobs to run on {len(resources)} resources"),
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression=" + ".join(value_terms)),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def _fits(self, job: dict[str, Any], resource: dict[str, Any]) -> bool:
        """Whether this resource can physically take this job."""
        for job_key, res_key in self._FIT_PAIRS:
            need = job.get(job_key)
            limit = resource.get(res_key)
            if need is not None and limit is not None and float(need) > float(limit):
                return False
        return True
