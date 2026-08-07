"""Capture SCIP's real branch-and-bound tree for the landing hero.

The hero needs something with volume that is also true. This is it: the actual
search tree of a real solve — every node SCIP opened, its parent, its depth, the
bound it carried, and how it ended (branched, infeasible, or cut off because its
bound could not beat the incumbent).

That last group is the point. Proving optimality means killing whole regions of
the search space without exploring them, and a tree that visibly prunes is both
spectacular and exactly what the product does.

    python scripts/gen_search_tree.py

Output: frontend/src/components/landing/data/searchTree.ts
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from pyscipopt import SCIP_EVENTTYPE, Eventhdlr, Model, quicksum

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "frontend" / "src" / "components" / "landing" / "data" / "searchTree.ts"

# Same instance family as the hero trace, sized up so the tree has real depth and
# real pruning instead of closing at the root.
STOPS = 30
SEED = 11


def build_points(n: int, seed: int) -> list[tuple[float, float]]:
    rng = random.Random(seed)
    return [(rng.random(), rng.random()) for _ in range(n)]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) * 100


class TreeRecorder(Eventhdlr):
    """Records the shape of the search: one entry per node SCIP focuses."""

    def __init__(self) -> None:
        super().__init__()
        self.nodes: dict[int, dict] = {}
        self.order: list[int] = []

    def eventinit(self) -> None:
        for event in (
            SCIP_EVENTTYPE.NODEFOCUSED,
            SCIP_EVENTTYPE.NODEFEASIBLE,
            SCIP_EVENTTYPE.NODEINFEASIBLE,
            SCIP_EVENTTYPE.NODEBRANCHED,
        ):
            self.model.catchEvent(event, self)

    def eventexec(self, event) -> None:  # noqa: ANN001 - PySCIPOpt callback signature
        model = self.model
        node = model.getCurrentNode()
        if node is None:
            return

        number = node.getNumber()
        parent = node.getParent()
        etype = event.getType()

        entry = self.nodes.get(number)
        if entry is None:
            entry = {
                "id": number,
                "parent": parent.getNumber() if parent is not None else None,
                "depth": node.getDepth(),
                "bound": node.getLowerbound(),
                "incumbent": model.getPrimalbound(),
                "outcome": "open",
            }
            self.nodes[number] = entry
            self.order.append(number)

        if etype == SCIP_EVENTTYPE.NODEBRANCHED:
            entry["outcome"] = "branched"
        elif etype == SCIP_EVENTTYPE.NODEINFEASIBLE:
            # SCIP reports both genuine infeasibility and bound-based cutoff here;
            # the bound tells them apart, and the distinction is the whole story.
            entry["outcome"] = "cutoff"
        elif etype == SCIP_EVENTTYPE.NODEFEASIBLE:
            entry["outcome"] = "feasible"


def solve() -> dict:
    points = build_points(STOPS, SEED)
    model = Model("tree")
    model.hideOutput()

    arcs = {
        (i, j): model.addVar(vtype="B", name=f"x_{i}_{j}")
        for i in range(STOPS)
        for j in range(STOPS)
        if i != j
    }
    order = {i: model.addVar(lb=0, ub=STOPS - 1, vtype="C") for i in range(STOPS)}

    for i in range(STOPS):
        model.addCons(quicksum(arcs[i, j] for j in range(STOPS) if j != i) == 1)
        model.addCons(quicksum(arcs[j, i] for j in range(STOPS) if j != i) == 1)
    for i in range(1, STOPS):
        for j in range(1, STOPS):
            if i != j:
                model.addCons(order[i] - order[j] + (STOPS - 1) * arcs[i, j] <= STOPS - 2)

    model.setObjective(
        quicksum(distance(points[i], points[j]) * arcs[i, j] for i, j in arcs), "minimize"
    )

    recorder = TreeRecorder()
    model.includeEventhdlr(recorder, "TreeRecorder", "records the search tree")
    model.optimize()

    optimum = model.getObjVal()
    nodes = [recorder.nodes[n] for n in recorder.order]

    # Normalise bounds to 0..1 across the tree so the scene can map them to height
    # without knowing anything about this instance's units.
    bounds = [n["bound"] for n in nodes if n["bound"] < 1e19]
    lo, hi = (min(bounds), max(bounds)) if bounds else (0.0, 1.0)
    span = (hi - lo) or 1.0

    for node in nodes:
        raw = node["bound"]
        node["bound"] = round(raw, 2) if raw < 1e19 else None
        node["t"] = round((raw - lo) / span, 4) if raw < 1e19 else 1.0
        node.pop("incumbent", None)

    return {
        "nodes": nodes,
        "meta": {
            "stops": STOPS,
            "total": len(nodes),
            "maxDepth": max((n["depth"] for n in nodes), default=0),
            "branched": sum(1 for n in nodes if n["outcome"] == "branched"),
            "cutoff": sum(1 for n in nodes if n["outcome"] == "cutoff"),
            "optimum": round(optimum, 2),
            "status": model.getStatus(),
            "solver": "SCIP",
        },
    }


def emit(data: dict) -> str:
    header = """// AUTO-GENERATED by scripts/gen_search_tree.py — do not edit by hand.
//
// SCIP's actual branch-and-bound tree on a real instance: every node it opened,
// its parent, its depth, the bound it carried, and how it ended. "cutoff" nodes
// are regions proven unable to beat the incumbent and killed without being
// explored — which is what proving optimality means.
//
// Regenerate with: python scripts/gen_search_tree.py

export type NodeOutcome = "branched" | "cutoff" | "feasible" | "open";

export interface TreeNode {
  readonly id: number;
  readonly parent: number | null;
  readonly depth: number;
  /** Dual bound carried by this node, or null when it had none yet. */
  readonly bound: number | null;
  /** Bound normalised to 0..1 across the tree, for mapping to space. */
  readonly t: number;
  readonly outcome: NodeOutcome;
}

export interface SearchTree {
  readonly nodes: readonly TreeNode[];
  readonly meta: {
    readonly stops: number;
    readonly total: number;
    readonly maxDepth: number;
    readonly branched: number;
    readonly cutoff: number;
    readonly optimum: number;
    readonly status: string;
    readonly solver: string;
  };
}

export const SEARCH_TREE: SearchTree = """
    return header + json.dumps(data, indent=2) + " as const;\n"


def main() -> None:
    data = solve()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(emit(data), encoding="utf-8")

    meta = data["meta"]
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    print(
        f"  {meta['total']} nodes, max depth {meta['maxDepth']}, "
        f"{meta['branched']} branched, {meta['cutoff']} cut off, "
        f"optimum {meta['optimum']} ({meta['status']})"
    )


if __name__ == "__main__":
    main()
