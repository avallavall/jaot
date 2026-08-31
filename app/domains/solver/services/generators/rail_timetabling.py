"""Rail timetabling generator — pick a departure minute for every train.

The card asks for a conflict-free timetable: every train departs once, trains
sharing a track segment keep a minimum headway between them, no segment takes
more trains per hour than it can hold, and the timetable stays as close to the
preferred departures as those rules allow.

The model is time-indexed. ``z[train, t]`` is 1 when that train departs at
minute ``t``. A train's route is the shortest path from its origin to its
destination through the segment graph, so two trains conflict exactly when
their paths share a segment. Entry into the k-th segment of a route happens
``travel_time * k / len(route)`` minutes after departure, which spreads the
stated journey time evenly over the segments it covers.

This used to reach the shift-covering scheduling generator. That model read no
preferred departure, no travel time, no priority, no headway and no capacity:
it staffed shifts with employees and reported the answer as a timetable.
"""

from collections import deque
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

#: trains x minutes. Past this the time-indexed formulation stops being the
#: right tool, and saying so beats handing the solver a model it times out on.
_MAX_DEPARTURE_VARS = 40_000


class RailTimetablingGenerator(BaseGenerator):
    """Choose departure minutes subject to headway and segment capacity."""

    _TRAIN_KEYS = ["trains", "services", "runs"]
    _SEGMENT_KEYS = ["track_segments", "segments", "sections", "blocks"]

    _TRAVEL_KEYS = ("travel_time", "travel_minutes", "journey_time", "runtime")
    _PREFERRED_KEYS = ("preferred_departure", "target_departure", "desired_departure")
    _PRIORITY_KEYS = ("priority", "weight", "importance")
    _HEADWAY_KEYS = ("min_headway", "headway", "headway_minutes")
    _CAPACITY_KEYS = ("capacity_per_hour", "trains_per_hour", "capacity")

    @staticmethod
    def _number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if row.get(key) is not None:
                return float(row[key])
        return None

    @staticmethod
    def _reject_collisions(sanitized: list[str], originals: list[Any], label: str) -> None:
        """Two rows whose names sanitize to the same identifier share variables."""
        by_name: dict[str, list[Any]] = {}
        for clean, original in zip(sanitized, originals, strict=True):
            by_name.setdefault(clean, []).append(original)
        clashes = {k: v for k, v in by_name.items() if len(v) > 1}
        if clashes:
            detail = "; ".join(f"{v} all become '{k}'" for k, v in sorted(clashes.items()))
            raise ValueError(f"{label} must have distinct names: {detail}.")

    @staticmethod
    def _endpoints(segment: dict[str, Any], index: int) -> tuple[str, str]:
        """The two stations a segment joins.

        An explicit from/to pair wins. Otherwise the name carries them, written
        "Amsterdam-Leiden".
        """
        for a_key, b_key in (("from", "to"), ("origin", "destination"), ("start", "end")):
            a, b = segment.get(a_key), segment.get(b_key)
            if a and b:
                return str(a).strip(), str(b).strip()

        name = str(segment.get("name", "")).strip()
        parts = [p.strip() for p in name.split("-") if p.strip()]
        if len(parts) != 2:
            raise ValueError(
                f"Track segment {index} ('{name or 'unnamed'}') does not say which two stations "
                "it joins. Give it a 'from' and a 'to', or name it 'Station A-Station B'."
            )
        return parts[0], parts[1]

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        trains = find_list_field(user_input, self._TRAIN_KEYS, fallback=False)
        segments = find_list_field(user_input, self._SEGMENT_KEYS, fallback=False)
        if not trains:
            raise ValueError(
                "Rail timetabling requires a list of trains "
                f"({', '.join(self._TRAIN_KEYS)}). Got keys: {list(user_input.keys())}"
            )
        if not segments:
            raise ValueError(
                "Rail timetabling requires a list of track segments "
                f"({', '.join(self._SEGMENT_KEYS)}). Got keys: {list(user_input.keys())}"
            )

        # The segment graph, and the adjacency used to walk a train's route.
        endpoints = [self._endpoints(s, i) for i, s in enumerate(segments)]
        neighbours: dict[str, list[tuple[str, int]]] = {}
        for s_index, (a, b) in enumerate(endpoints):
            neighbours.setdefault(a, []).append((b, s_index))
            neighbours.setdefault(b, []).append((a, s_index))

        travel: list[int] = []
        for i, train in enumerate(trains):
            minutes = self._number(train, self._TRAVEL_KEYS)
            if minutes is None or minutes <= 0:
                raise ValueError(
                    f"Train '{train.get('name', i)}' has no positive travel time. "
                    f"Expected one of: {', '.join(self._TRAVEL_KEYS)}."
                )
            travel.append(max(1, int(round(minutes))))

        stated = self._number(user_input, ("time_horizon", "horizon", "planning_minutes"))
        horizon = int(stated) if stated is not None else max(travel) * len(trains)
        if horizon <= 0:
            raise ValueError("Rail timetabling needs a positive time horizon in minutes.")

        routes = [self._route(train, i, neighbours) for i, train in enumerate(trains)]

        names = [self.sanitize_name(t.get("name", f"train_{i}")) for i, t in enumerate(trains)]
        seg_names = [
            self.sanitize_name(s.get("name", f"segment_{i}")) for i, s in enumerate(segments)
        ]
        # "IC-201" and "IC 201" both sanitize to ic_201, and their departure
        # variables would then be the same variable. Say so instead of building
        # a model that silently times one train and drops the other.
        self._reject_collisions(names, [t.get("name") for t in trains], "Trains")
        self._reject_collisions(seg_names, [s.get("name") for s in segments], "Track segments")

        # A train must be clear of the network before the horizon closes.
        slots: list[list[int]] = []
        variables: list[Variable] = []
        for i, name in enumerate(names):
            latest = horizon - travel[i]
            if latest < 0:
                raise ValueError(
                    f"Train '{trains[i].get('name', i)}' needs {travel[i]} minutes but the "
                    f"horizon is {horizon}. No departure fits."
                )
            times = list(range(latest + 1))
            slots.append(times)
            variables.extend(
                Variable(name=f"z_{name}_{t}", type=VariableType.BINARY) for t in times
            )

        if len(variables) > _MAX_DEPARTURE_VARS:
            raise ValueError(
                f"Rail timetabling would need {len(variables):,} departure variables "
                f"(limit {_MAX_DEPARTURE_VARS:,}). Shorten the horizon or the train list."
            )

        constraints: list[Constraint] = []

        # Every train departs exactly once.
        for i, name in enumerate(names):
            departures = " + ".join(f"z_{name}_{t}" for t in slots[i])
            constraints.append(
                Constraint(name=f"departs_once_{name}", expression=f"{departures} == 1")
            )

        # When each train enters each segment of its route, relative to its
        # departure. The journey time is spread evenly over the route.
        entry_offset: list[dict[int, int]] = []
        for i, route in enumerate(routes):
            entry_offset.append(
                {
                    s_index: int(round(travel[i] * position / len(route)))
                    for position, s_index in enumerate(route)
                }
            )

        # Headway: at most one train enters a segment in any window of
        # min_headway consecutive minutes. A headway of 1 still says something —
        # two trains may not enter in the same minute — so only a headway below
        # one minute is nothing to enforce.
        for s_index, segment in enumerate(segments):
            headway = self._number(segment, self._HEADWAY_KEYS)
            if headway is None or headway < 1:
                continue
            width = int(round(headway))
            users = [i for i in range(len(trains)) if s_index in entry_offset[i]]
            if len(users) < 2:
                continue
            for start in range(horizon + 1):
                entering = [
                    f"z_{names[i]}_{t}"
                    for i in users
                    for t in slots[i]
                    if start <= t + entry_offset[i][s_index] < start + width
                ]
                if len(entering) > 1:
                    constraints.append(
                        Constraint(
                            name=f"headway_{seg_names[s_index]}_{start}",
                            expression=f"{' + '.join(entering)} <= 1",
                        )
                    )

        # Capacity: no more than capacity_per_hour trains enter a segment in
        # any 60-minute window.
        for s_index, segment in enumerate(segments):
            per_hour = self._number(segment, self._CAPACITY_KEYS)
            if per_hour is None:
                continue
            if per_hour < 0:
                raise ValueError(
                    f"Track segment '{segment.get('name', s_index)}' states a capacity of "
                    f"{per_hour} trains an hour. A negative capacity has no timetable; say 0 "
                    "if the segment is closed."
                )
            limit = int(per_hour)
            users = [i for i in range(len(trains)) if s_index in entry_offset[i]]
            if not users or limit >= len(users):
                continue
            for start in range(max(1, horizon - 58)):
                entering = [
                    f"z_{names[i]}_{t}"
                    for i in users
                    for t in slots[i]
                    if start <= t + entry_offset[i][s_index] < start + 60
                ]
                if len(entering) > limit:
                    constraints.append(
                        Constraint(
                            name=f"capacity_{seg_names[s_index]}_{start}",
                            expression=f"{' + '.join(entering)} <= {limit}",
                        )
                    )

        # A readable departure minute per train, so the answer names the time.
        for i, name in enumerate(names):
            variables.append(
                Variable(
                    name=f"departure_{name}",
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=horizon,
                )
            )
            weighted = " + ".join(f"{t}*z_{name}_{t}" for t in slots[i] if t > 0)
            constraints.append(
                Constraint(
                    name=f"departure_def_{name}",
                    expression=f"departure_{name} - ({weighted}) == 0"
                    if weighted
                    else f"departure_{name} == 0",
                )
            )

        # Deviation from the preferred departure, weighted by priority. A train
        # nobody stated a preference for is content anywhere.
        terms: list[str] = []
        for i, train in enumerate(trains):
            preferred = self._number(train, self._PREFERRED_KEYS)
            if preferred is None:
                continue
            priority = self._number(train, self._PRIORITY_KEYS)
            weight = 1.0 if priority is None else priority
            for t in slots[i]:
                cost = weight * abs(t - preferred)
                if cost:
                    terms.append(f"{cost}*z_{names[i]}_{t}")

        return OptimizationProblem(
            name="rail_timetabling",
            description=(
                f"Time {len(trains)} trains over {len(segments)} track segments "
                f"in a {horizon}-minute window"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(terms) if terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def _route(
        self,
        train: dict[str, Any],
        index: int,
        neighbours: dict[str, list[tuple[str, int]]],
    ) -> list[int]:
        """The segments a train covers, in order, origin to destination."""
        origin = str(train.get("origin", "")).strip()
        destination = str(train.get("destination", "")).strip()
        label = train.get("name", index)
        if not origin or not destination:
            raise ValueError(f"Train '{label}' needs both an origin and a destination.")
        for station in (origin, destination):
            if station not in neighbours:
                raise ValueError(
                    f"Train '{label}' calls at '{station}', which no track segment reaches. "
                    f"Known stations: {', '.join(sorted(neighbours))}."
                )
        if origin == destination:
            raise ValueError(f"Train '{label}' departs from and arrives at '{origin}'.")

        # Breadth-first, so the route is the one crossing the fewest segments.
        queue: deque[tuple[str, list[int]]] = deque([(origin, [])])
        seen = {origin}
        while queue:
            station, path = queue.popleft()
            for nxt, s_index in neighbours[station]:
                if nxt in seen:
                    continue
                if nxt == destination:
                    return [*path, s_index]
                seen.add(nxt)
                queue.append((nxt, [*path, s_index]))

        raise ValueError(
            f"Train '{label}' has no route from '{origin}' to '{destination}' "
            "through the track segments given."
        )
