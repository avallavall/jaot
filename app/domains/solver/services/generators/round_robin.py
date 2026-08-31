"""Round-robin generator — who plays whom, on which matchday, at whose ground.

Every pair of teams meets exactly once. The model decides three things at the
same time: which matchday each fixture lands on, which of the two teams hosts
it, and therefore who travels.

Hosting is what the objective turns on. The visiting club pays the road, and
clubs do not pay the same rate per kilometre — squad size and coach hire differ
— so sending the cheaper traveller is worth money. A home-and-away balance rule
stops the answer from being fifteen separate two-way choices: each club has to
host either floor((n-1)/2) or ceil((n-1)/2) of its games, so hosting is a
scarce thing the schedule has to share out.

Note what this generator does NOT do, because the difference is a research
problem and not a rounding error. A DOUBLE round robin, where each ordered pair
plays once, has a constant travel total: every club visits every other club
exactly once whatever the schedule, so the objective cannot tell two answers
apart. Real double-round-robin travel optimisation (the travelling tournament
problem) only becomes non-trivial once a club on consecutive away games drives
host-to-host instead of going home in between, and that needs a location
variable per club per matchday. This card is the single round robin.

This used to reach the shift-covering scheduling generator. Every team was an
"employee" with ``hourly_cost: 1`` and every slot was a "shift", so the
objective counted shifts, every fixture list tied for optimal, and no pair was
ever guaranteed to meet.
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

#: ordered pairs x matchdays. Past this the fixture model stops being the right
#: tool, and saying so beats handing the solver a model it will time out on.
_MAX_FIXTURE_VARS = 20_000


class RoundRobinGenerator(BaseGenerator):
    """Build a single round-robin fixture list and choose every host."""

    _TEAM_KEYS = ["teams", "clubs", "participants", "competitors"]
    _DISTANCE_KEYS = ["distances", "travel_distances", "legs", "routes"]

    _RATE_KEYS = ("travel_cost_per_km", "cost_per_km", "travel_rate", "coach_cost_per_km")
    _ROUND_KEYS = ("rounds", "matchdays", "match_days", "num_rounds")
    _RUN_KEYS = ("max_consecutive_away", "max_away_run", "max_consecutive_away_games")

    _FROM_KEYS = ("from", "from_team", "origin", "a", "team_a")
    _TO_KEYS = ("to", "to_team", "destination", "b", "team_b")
    _KM_KEYS = ("km", "distance", "distance_km", "travel_km", "miles")

    @staticmethod
    def _text(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            if row.get(key):
                return str(row[key])
        return None

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        teams = find_list_field(user_input, self._TEAM_KEYS, fallback=False)
        if len(teams) < 2:
            raise ValueError(
                "A round robin needs at least two teams "
                f"({', '.join(self._TEAM_KEYS)}). Got keys: {list(user_input.keys())}"
            )

        names = [self.sanitize_name(t.get("name", f"team_{i}")) for i, t in enumerate(teams)]
        self.reject_name_collisions(names, [t.get("name") for t in teams], "Teams")

        n = len(teams)
        games = n * (n - 1) // 2

        # A matchday fits at most n // 2 games, so the season needs enough of
        # them to hold every fixture.
        stated_rounds = self.first_number(user_input, self._ROUND_KEYS)
        rounds = int(stated_rounds) if stated_rounds is not None else (n - 1 if n % 2 == 0 else n)
        if rounds <= 0:
            raise ValueError("A round robin needs a positive number of matchdays.")
        if rounds * (n // 2) < games:
            raise ValueError(
                f"{rounds} matchdays hold at most {rounds * (n // 2)} games, but {n} teams "
                f"playing each other once is {games} games. Add matchdays."
            )

        max_away_run = self.first_number(user_input, self._RUN_KEYS)
        if max_away_run is not None and max_away_run < 1:
            raise ValueError(
                "max_consecutive_away must be at least 1: a team that may never play two "
                "away games in a row still has to play away sometimes."
            )

        distances = self._distance_table(user_input, names, teams)
        rates = self._rates(teams, names)

        if n * (n - 1) * rounds > _MAX_FIXTURE_VARS:
            raise ValueError(
                f"This season would need {n * (n - 1) * rounds:,} fixture variables "
                f"(limit {_MAX_FIXTURE_VARS:,}). Fewer teams or fewer matchdays."
            )

        def host(i: int, j: int, r: int) -> str:
            """i hosts j on matchday r."""
            return f"h_{names[i]}_v_{names[j]}_r{r}"

        variables: list[Variable] = [
            Variable(name=host(i, j, r), type=VariableType.BINARY)
            for i in range(n)
            for j in range(n)
            if i != j
            for r in range(rounds)
        ]
        constraints: list[Constraint] = []

        # Every pair meets exactly once, one way round or the other.
        #
        # Named by index, not by the two team names. A sanitized name is made of
        # letters, digits and underscores, so any separator built from those can
        # itself appear inside a name: teams {a, b_c} and {a_b, c} would both
        # produce "meet_a_b_c". The solver applies both constraints either way,
        # so the answer stays right, but sensitivity output is reported per
        # constraint name and two rows would share one. The fixture variables
        # carry the readable names.
        for i in range(n):
            for j in range(i + 1, n):
                both = [host(i, j, r) for r in range(rounds)] + [
                    host(j, i, r) for r in range(rounds)
                ]
                constraints.append(
                    Constraint(
                        name=f"meet_{i}_{j}",
                        expression=f"{' + '.join(both)} == 1",
                    )
                )

        # A team plays at most one game per matchday.
        for i in range(n):
            for r in range(rounds):
                playing = [host(i, j, r) for j in range(n) if j != i] + [
                    host(j, i, r) for j in range(n) if j != i
                ]
                constraints.append(
                    Constraint(
                        name=f"one_game_{names[i]}_r{r}",
                        expression=f"{' + '.join(playing)} <= 1",
                    )
                )

        # Home and away balance: each team hosts as near half its games as an
        # odd count allows.
        low, high = (n - 1) // 2, (n - 1 + 1) // 2
        for i in range(n):
            hosted = [host(i, j, r) for j in range(n) if j != i for r in range(rounds)]
            joined = " + ".join(hosted)
            constraints.append(
                Constraint(name=f"hosts_at_least_{names[i]}", expression=f"{joined} >= {low}")
            )
            constraints.append(
                Constraint(name=f"hosts_at_most_{names[i]}", expression=f"{joined} <= {high}")
            )

        # No long road trips: at most `max_consecutive_away` away games in any
        # window of one more matchday than that.
        if max_away_run is not None:
            run = int(max_away_run)
            for i in range(n):
                for start in range(rounds - run):
                    away = [
                        host(j, i, r)
                        for r in range(start, start + run + 1)
                        for j in range(n)
                        if j != i
                    ]
                    constraints.append(
                        Constraint(
                            name=f"away_run_{names[i]}_r{start}",
                            expression=f"{' + '.join(away)} <= {run}",
                        )
                    )

        # A readable home-game count per team, so the answer shows the balance.
        for i in range(n):
            variables.append(
                Variable(
                    name=f"home_games_{names[i]}",
                    type=VariableType.INTEGER,
                    lower_bound=0,
                    upper_bound=n - 1,
                )
            )
            hosted = " + ".join(host(i, j, r) for j in range(n) if j != i for r in range(rounds))
            constraints.append(
                Constraint(
                    name=f"home_games_def_{names[i]}",
                    expression=f"home_games_{names[i]} - ({hosted}) == 0",
                )
            )

        # The visitor pays the road, at its own rate per kilometre.
        terms = [
            f"{round(distances[(i, j)] * rates[j], 6)}*{host(i, j, r)}"
            for i in range(n)
            for j in range(n)
            if i != j
            for r in range(rounds)
        ]

        return OptimizationProblem(
            name="round_robin_fixtures",
            description=(
                f"Draw {games} fixtures for {n} teams over {rounds} matchdays, "
                "choosing hosts to cut visitor travel"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(terms) if terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def _rates(self, teams: list[dict[str, Any]], names: list[str]) -> list[float]:
        """What a kilometre on the road costs each club."""
        rates: list[float] = []
        for i, team in enumerate(teams):
            rate = self.first_number(team, self._RATE_KEYS)
            if rate is None or rate <= 0:
                raise ValueError(
                    f"Team '{team.get('name', names[i])}' has no positive travel cost per "
                    f"kilometre. Expected one of: {', '.join(self._RATE_KEYS)}."
                )
            rates.append(rate)
        return rates

    def _distance_table(
        self,
        user_input: dict[str, Any],
        names: list[str],
        teams: list[dict[str, Any]],
    ) -> dict[tuple[int, int], float]:
        """Road distance between every pair, both ways round.

        Rows are written with the names the card uses, and variable names are
        sanitized, so the lookup sanitizes both sides. Reading the table with
        the raw text is how four other generators silently priced every leg at
        a hardcoded default.
        """
        rows = find_list_field(user_input, self._DISTANCE_KEYS, fallback=False)
        index = {name: i for i, name in enumerate(names)}
        table: dict[tuple[int, int], float] = {}

        for row in rows:
            a = self._text(row, self._FROM_KEYS)
            b = self._text(row, self._TO_KEYS)
            km = self.first_number(row, self._KM_KEYS)
            if a is None or b is None or km is None:
                raise ValueError(
                    f"Distance row {row!r} needs a from, a to and a distance. "
                    f"Expected keys like {self._FROM_KEYS[0]} / {self._TO_KEYS[0]} / "
                    f"{self._KM_KEYS[0]}."
                )
            i, j = index.get(self.sanitize_name(a)), index.get(self.sanitize_name(b))
            if i is None or j is None:
                unknown = a if i is None else b
                raise ValueError(
                    f"Distance row names '{unknown}', which is not one of the teams: "
                    f"{', '.join(str(t.get('name')) for t in teams)}."
                )
            table[(i, j)] = km
            table.setdefault((j, i), km)

        missing = [
            f"{teams[i].get('name')} - {teams[j].get('name')}"
            for i in range(len(names))
            for j in range(i + 1, len(names))
            if (i, j) not in table
        ]
        if missing:
            raise ValueError(
                f"No distance given for {len(missing)} pair(s): {'; '.join(missing[:5])}. "
                "Every pair travels, so every pair needs a distance."
            )
        return table
