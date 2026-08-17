"""Generate the landing page's solver-comparison showcase with the real solvers.

The "which solver" section on the home page shows one problem run by SCIP,
HiGHS, CBC and GLPK under the terms the product itself imposes: the same time
limit, the same gap tolerance, the same thread count, one run after another on
one machine. The numbers on the page are what these adapters returned — the
same code path ``/api/v2/solvers/compare`` uses, not a re-implementation.

The instance is a burn-in chamber loading plan for the power-electronics plant
the rest of the landing page already solves: every finished lot has to spend a
fixed number of hours in a thermal chamber before it ships, and the plant wants
to bring up as few chambers as possible for the quarter. It is a bin-packing
model, which is deliberate — the assignment is symmetric (any lot fits any
chamber), and how a solver handles that symmetry is exactly what separates them.

Run it inside the comparison worker, which is the only image carrying all four
solvers. Its root filesystem is read-only, so feed the script on stdin rather
than copying it in, and redirect the result:

    docker exec -i jaot_celery_compare python - \\
      < scripts/gen_landing_comparison.py \\
      > frontend/src/components/landing/data/comparisonShowcase.ts

Read from stdin there is no ``__file__``, and nothing is writable anyway, so the
script prints the TypeScript to stdout whenever it cannot write the file itself.

Output: frontend/src/components/landing/data/comparisonShowcase.ts
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from app.domains.solver.adapters import register_default_adapters, registry
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


def _output_path() -> Path | None:
    """Where to write, or None when the script was fed on stdin (no ``__file__``)."""
    try:
        root = Path(__file__).resolve().parent.parent
    except NameError:
        return None
    return root / "frontend" / "src" / "components" / "landing" / "data" / "comparisonShowcase.ts"


#: The terms every solver receives. These are the comparer's own defaults for a
#: run of this size; the thread count is fixed by the platform because HiGHS
#: settles its own on the first solve of a process.
TIME_LIMIT_SECONDS = 60.0
GAP_TOLERANCE = 0.0001
THREADS = 4

#: The quarter's lots, by product family: how many, and how many hours each of
#: them has to spend in a chamber. Written out rather than generated, so the
#: same run gives the same numbers. A traction inverter needs a full 60-hour
#: cycle, which is what makes the packing hard — a chamber runs 168 hours, so
#: two of them fit and three never do, and every chamber that takes two wastes
#: the best part of two days.
LOT_FAMILIES = [
    ("tractionInverter", 17, 60),
    ("batteryMonitor", 13, 58),
    ("chargeModule", 11, 45),
    ("sensorBoard", 10, 30),
    ("gateDriver", 9, 22),
]

LOT_HOURS = [hours for _family, count, hours in LOT_FAMILIES for _ in range(count)]

#: Hours one chamber can run in the quarter, after its maintenance windows.
CHAMBER_HOURS = 168

#: Chambers the plant could bring up. Above the obvious lower bound so the
#: solver has something to prove, below the trivial one-lot-per-chamber answer.
CHAMBERS = 22

#: How the shared vibration fixtures are spread over the lots. A fixture cannot
#: sit in two racks at once, so two lots that need the same one cannot share a
#: chamber. This is what makes the plan hard: without it the packing falls out
#: of the LP relaxation at the root node and every solver answers in a tenth of
#: a second. The strides are written out so the same run gives the same numbers.
FIXTURE_STRIDES = (7, 11, 13)


def fixture_conflicts() -> list[tuple[int, int]]:
    """Pairs of lots that need the same fixture, so they cannot share a chamber."""
    pairs: set[tuple[int, int]] = set()
    count = len(LOT_HOURS)
    for lot in range(count):
        for stride in FIXTURE_STRIDES:
            other = (lot * stride + 3) % count
            if other != lot:
                pairs.add((min(lot, other), max(lot, other)))
    return sorted(pairs)


SOLVERS = ["scip", "highs", "cbc", "glpk"]


def build_problem() -> OptimizationProblem:
    """One binary per (lot, chamber) plus one per chamber, minimize chambers used."""
    variables: list[Variable] = []
    for chamber in range(CHAMBERS):
        variables.append(Variable(name=f"chamber_{chamber}", type=VariableType.BINARY))
        for lot in range(len(LOT_HOURS)):
            variables.append(Variable(name=f"load_{lot}_{chamber}", type=VariableType.BINARY))

    constraints: list[Constraint] = []
    # Every lot goes into exactly one chamber.
    for lot in range(len(LOT_HOURS)):
        terms = " + ".join(f"load_{lot}_{c}" for c in range(CHAMBERS))
        constraints.append(Constraint(name=f"lot_{lot}_placed", expression=f"{terms} == 1"))

    # A chamber cannot run longer than its available hours, and a chamber that
    # takes any lot at all counts as brought up.
    for chamber in range(CHAMBERS):
        terms = " + ".join(f"{hours}*load_{lot}_{chamber}" for lot, hours in enumerate(LOT_HOURS))
        constraints.append(
            Constraint(
                name=f"chamber_{chamber}_hours",
                expression=f"{terms} - {CHAMBER_HOURS}*chamber_{chamber} <= 0",
            )
        )

    # Two lots that need the same fixture cannot sit in one chamber.
    for left, right in fixture_conflicts():
        for chamber in range(CHAMBERS):
            constraints.append(
                Constraint(
                    name=f"fixture_{left}_{right}_{chamber}",
                    expression=f"load_{left}_{chamber} + load_{right}_{chamber} <= 1",
                )
            )

    return OptimizationProblem(
        name="burn_in_chamber_plan",
        objective=Objective(
            sense=ObjectiveSense.MINIMIZE,
            expression=" + ".join(f"chamber_{c}" for c in range(CHAMBERS)),
        ),
        variables=variables,
        constraints=constraints,
        options=SolverOptions(
            time_limit_seconds=TIME_LIMIT_SECONDS,
            gap_tolerance=GAP_TOLERANCE,
            threads=THREADS,
        ),
    )


def run_one(name: str, problem: OptimizationProblem) -> dict[str, object]:
    """Solve with one adapter and record what the comparer's table would show."""
    adapter = registry.get(name)
    started = time.perf_counter()
    result = adapter.solve(problem)
    wall_ms = int(round((time.perf_counter() - started) * 1000))
    return {
        "solver": name,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "objective": result.objective_value,
        "bound": result.dual_bound,
        "gap": result.gap,
        "wallMs": wall_ms,
        "searchSeconds": result.solve_time_seconds,
        "nodes": result.nodes,
        "iterations": result.iterations,
    }


#: Verdicts whose seconds mean something. A run that came back with no answer
#: was not "fast", it was cut off — the same rule ``ComparisonTable.fastestOf``
#: applies in the product.
SOLVED_STATUSES = frozenset({"optimal", "feasible"})


def emit(rows: list[dict[str, object]]) -> str:
    """Render the TypeScript module the landing component imports."""
    answered = [r for r in rows if r["status"] in SOLVED_STATUSES and r["wallMs"] is not None]
    fastest_ms = min(int(r["wallMs"]) for r in answered) if len(answered) > 1 else 0
    for row in rows:
        row["slowdown"] = (
            round(int(row["wallMs"]) / fastest_ms, 2)
            if fastest_ms and row["status"] in SOLVED_STATUSES
            else None
        )

    payload = json.dumps(rows, indent=2)
    meta = json.dumps(
        {
            "lots": len(LOT_HOURS),
            "chambers": CHAMBERS,
            "chamberHours": CHAMBER_HOURS,
            "fixturePairs": len(fixture_conflicts()),
            "variables": CHAMBERS * (len(LOT_HOURS) + 1),
            "constraints": len(LOT_HOURS) + CHAMBERS + len(fixture_conflicts()) * CHAMBERS,
            "timeLimitSeconds": TIME_LIMIT_SECONDS,
            "gapTolerance": GAP_TOLERANCE,
            "threads": THREADS,
            # The machine, described rather than named: the hostname is not the
            # public's business, and the core count is the part that matters for
            # reading the seconds.
            "cores": os.cpu_count() or 0,
        },
        indent=2,
    )
    return f"""// AUTO-GENERATED by scripts/gen_landing_comparison.py — do not edit by hand.
//
// One real problem run by all four solvers under the terms the comparer
// imposes: same time limit, same gap tolerance, same thread count, one after
// another on one machine. The numbers are what JAOT's own adapters returned.
//
// The instance is a burn-in chamber loading plan for the same power-electronics
// plant the rest of this page solves. It is a bin-packing model on purpose: the
// assignment is symmetric, and how a solver handles that symmetry is what
// separates the four.
//
// Regenerate with: python scripts/gen_landing_comparison.py

export interface ComparisonRow {{
  readonly solver: string;
  /** The solver's own verdict: optimal | feasible | time_limit | ... */
  readonly status: string;
  readonly objective: number | null;
  /** Best objective the solver proved could still exist. */
  readonly bound: number | null;
  readonly gap: number | null;
  /** Wall time around the whole call, building the solver's model included. */
  readonly wallMs: number;
  /** The adapter's own measure of the search alone. */
  readonly searchSeconds: number | null;
  readonly nodes: number | null;
  readonly iterations: number | null;
  /** How many times slower than the quickest solver that actually answered.
   *  Null for a run that came back without one: it was cut off, not slow. */
  readonly slowdown: number | null;
}}

export interface ComparisonShowcaseMeta {{
  readonly lots: number;
  readonly chambers: number;
  readonly chamberHours: number;
  /** Pairs of lots that share a fixture and so cannot share a chamber. */
  readonly fixturePairs: number;
  readonly variables: number;
  readonly constraints: number;
  readonly timeLimitSeconds: number;
  readonly gapTolerance: number;
  readonly threads: number;
  /** Cores on the machine that produced these seconds. */
  readonly cores: number;
}}

export const COMPARISON_ROWS: readonly ComparisonRow[] = {payload} as const;

export const COMPARISON_META: ComparisonShowcaseMeta = {meta} as const;
"""


def main() -> None:
    register_default_adapters()
    problem = build_problem()
    rows = [run_one(name, problem) for name in SOLVERS]
    source = emit(rows)
    output = _output_path()
    if output is None:
        print(source)
        return
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(source, encoding="utf-8")
        print(f"Wrote {output}", file=sys.stderr)
    except OSError:
        # Running inside the worker image, whose filesystem is read-only.
        print(source)


if __name__ == "__main__":
    main()
