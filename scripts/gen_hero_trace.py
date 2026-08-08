"""Generate the landing hero's solve trace with the real solver.

The home page hero animates an actual optimization run: every tour it draws is a
solution SCIP found, and every bound is one SCIP proved. Nothing is invented, so
the numbers on the front page survive someone checking them.

Run it when the visual needs regenerating (it is deterministic — same seed, same
trace) and commit the emitted TypeScript:

    python scripts/gen_hero_trace.py

Output: frontend/src/components/landing/data/heroTrace.ts
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from pyscipopt import SCIP_EVENTTYPE, Eventhdlr, Model, quicksum

# 48 stops: a full delivery round rather than a demonstration. It is also where
# the two demands meet — the tangle has to read at a glance in a 100×100 SVG,
# and SCIP has to *prove* optimality on a Miller-Tucker-Zemlin model, which gets
# expensive fast (24 stops: 102 nodes; 48: ~850; 60: ~4,350 and over a minute).
STOPS = 48
SEED = 7
VIEWBOX = 100.0
MARGIN = 6.0
# The hero replays one improving tour per beat, so a long trace turns the visual
# into a wait. Incumbents that barely move the picture are dropped and, if the
# trace is still long, what remains is subsampled evenly. The first incumbent and
# the proven optimum always survive — every tour drawn is still one SCIP found.
MAX_FRAMES = 6
# SCIP improves the last incumbent by fractions of a percent while it closes the
# tree. Those steps cost a beat each and are invisible at hero size.
MIN_IMPROVEMENT = 0.02

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "src"
    / "components"
    / "landing"
    / "data"
    / "heroTrace.ts"
)


def build_points(n: int, seed: int) -> list[tuple[float, float]]:
    """Deterministic stops, inset from the edges so strokes never clip."""
    rng = random.Random(seed)
    span = VIEWBOX - 2 * MARGIN
    return [(MARGIN + rng.random() * span, MARGIN + rng.random() * span) for _ in range(n)]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class TraceRecorder(Eventhdlr):
    """Records every improving tour and the dual bound as the search closes."""

    def __init__(self, arcs: dict[tuple[int, int], object], n: int) -> None:
        super().__init__()
        self.arcs = arcs
        self.n = n
        self.frames: list[dict] = []
        self.bounds: list[dict] = []

    def eventinit(self) -> None:
        self.model.catchEvent(SCIP_EVENTTYPE.BESTSOLFOUND, self)
        self.model.catchEvent(SCIP_EVENTTYPE.NODESOLVED, self)

    def eventexec(self, event) -> None:  # noqa: ANN001 - PySCIPOpt callback signature
        model = self.model
        dual = model.getDualbound()

        if event.getType() == SCIP_EVENTTYPE.BESTSOLFOUND:
            sol = model.getBestSol()
            successor = {
                i: j for (i, j), var in self.arcs.items() if model.getSolVal(sol, var) > 0.5
            }
            tour, seen, current = [0], {0}, 0
            while successor.get(current) is not None and successor[current] not in seen:
                current = successor[current]
                tour.append(current)
                seen.add(current)
            if len(tour) == self.n:
                self.frames.append(
                    {
                        "tour": tour,
                        "cost": round(model.getSolObjVal(sol), 2),
                        "dual": round(max(dual, 0.0), 2),
                        "nodes": model.getNNodes(),
                    }
                )

        self.bounds.append(
            {
                "nodes": model.getNNodes(),
                "primal": model.getPrimalbound(),
                "dual": max(dual, 0.0),
            }
        )


def thin(frames: list[dict]) -> list[dict]:
    """Reduce the trace to the incumbents worth animating.

    The first and the last are always kept: the hero's whole argument is the
    distance between the first answer and the proven one.
    """
    kept = [frames[0]]
    for frame in frames[1:-1]:
        if (kept[-1]["cost"] - frame["cost"]) / kept[-1]["cost"] >= MIN_IMPROVEMENT:
            kept.append(frame)
    kept.append(frames[-1])

    if len(kept) <= MAX_FRAMES:
        return kept
    step = (len(kept) - 1) / (MAX_FRAMES - 1)
    picked = sorted({round(k * step) for k in range(MAX_FRAMES)} | {0, len(kept) - 1})
    return [kept[k] for k in picked]


def solve() -> dict:
    points = build_points(STOPS, SEED)
    model = Model("hero-tour")
    model.hideOutput()

    arcs = {
        (i, j): model.addVar(vtype="B", name=f"x_{i}_{j}")
        for i in range(STOPS)
        for j in range(STOPS)
        if i != j
    }
    order = {i: model.addVar(lb=0, ub=STOPS - 1, vtype="C", name=f"u_{i}") for i in range(STOPS)}

    for i in range(STOPS):
        model.addCons(quicksum(arcs[i, j] for j in range(STOPS) if j != i) == 1)
        model.addCons(quicksum(arcs[j, i] for j in range(STOPS) if j != i) == 1)
    # Miller-Tucker-Zemlin: compact subtour elimination, no lazy separation, so
    # the run stays reproducible across SCIP builds.
    for i in range(1, STOPS):
        for j in range(1, STOPS):
            if i != j:
                model.addCons(order[i] - order[j] + (STOPS - 1) * arcs[i, j] <= STOPS - 2)

    model.setObjective(
        quicksum(distance(points[i], points[j]) * arcs[i, j] for i, j in arcs), "minimize"
    )

    recorder = TraceRecorder(arcs, STOPS)
    model.includeEventhdlr(recorder, "TraceRecorder", "records tours and bounds")
    model.optimize()

    optimum = round(model.getObjVal(), 2)
    # The proof only lands when the tree is exhausted, after the last incumbent —
    # that trailing stretch is the whole point of the hero, so keep it.
    curve = [
        {
            "nodes": b["nodes"],
            "dual": round(b["dual"], 2),
            "primal": round(b["primal"], 2) if b["primal"] < 1e19 else None,
        }
        for b in recorder.bounds
    ]

    return {
        "points": [[round(x, 2), round(y, 2)] for x, y in points],
        "frames": thin(recorder.frames),
        "curve": curve,
        "meta": {
            "stops": STOPS,
            "variables": len(arcs) + len(order),
            "binaries": len(arcs),
            "optimum": optimum,
            "nodes": model.getNNodes(),
            "status": model.getStatus(),
            "solver": "SCIP",
        },
    }


def emit(trace: dict) -> str:
    header = f"""// AUTO-GENERATED by scripts/gen_hero_trace.py — do not edit by hand.
//
// Every tour below is a solution SCIP actually found on a {STOPS}-stop routing
// instance (seed {SEED}), and every bound is one it proved. The hero animates
// this trace, so the front page shows a real run rather than a mock-up.
//
// Regenerate with: python scripts/gen_hero_trace.py

export interface HeroTraceFrame {{
  /** Stop indices in visiting order, closing back to the first. */
  readonly tour: readonly number[];
  /** Objective value of this incumbent (total route length). */
  readonly cost: number;
  /** Best proven lower bound when this incumbent was found. */
  readonly dual: number;
  /** Branch-and-bound nodes explored at that moment. */
  readonly nodes: number;
}}

export interface HeroTraceCurvePoint {{
  readonly nodes: number;
  readonly dual: number;
  readonly primal: number | null;
}}

export interface HeroTrace {{
  readonly points: readonly (readonly [number, number])[];
  readonly frames: readonly HeroTraceFrame[];
  readonly curve: readonly HeroTraceCurvePoint[];
  readonly meta: {{
    readonly stops: number;
    readonly variables: number;
    readonly binaries: number;
    readonly optimum: number;
    readonly nodes: number;
    readonly status: string;
    readonly solver: string;
  }};
}}

export const HERO_TRACE: HeroTrace = """
    return header + json.dumps(trace, indent=2) + " as const;\n"


def main() -> None:
    trace = solve()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(emit(trace), encoding="utf-8")

    meta = trace["meta"]
    print(f"Wrote {OUTPUT.relative_to(Path(__file__).resolve().parent.parent)}")
    print(
        f"  {meta['stops']} stops · {meta['variables']} variables "
        f"({meta['binaries']} binary) · {meta['nodes']} nodes · {meta['status']}"
    )
    for k, frame in enumerate(trace["frames"]):
        gap = (frame["cost"] - frame["dual"]) / frame["cost"] * 100
        print(
            f"  frame {k}: cost={frame['cost']:.2f} dual={frame['dual']:.2f} "
            f"gap={gap:.2f}% at node {frame['nodes']}"
        )
    print(f"  curve samples: {len(trace['curve'])}")


if __name__ == "__main__":
    main()
