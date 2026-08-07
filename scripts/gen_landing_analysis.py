"""Generate the landing page's exact-analysis showcase with the real solver.

The "understand your solution" section shows what JAOT actually computes after a
solve: which constraints are binding, how much slack is left on the others, and
what each objective term contributes. Those are computed from the solution x*
and the problem data — b_i − a_i·x* and c_j·x*_j — exactly as
app/domains/solver/services/exact_analysis.py does, and deliberately NOT as
LP-relaxation shadow prices, which are duals of an easier problem and go
near-uniform under degeneracy.

Deterministic: the instance is written out by hand, so the same run gives the
same numbers. Regenerate and commit the emitted TypeScript:

    python scripts/gen_landing_analysis.py

Output: frontend/src/components/landing/data/analysisShowcase.ts
"""

from __future__ import annotations

import json
from pathlib import Path

from pyscipopt import Model, quicksum

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "src"
    / "components"
    / "landing"
    / "data"
    / "analysisShowcase.ts"
)

# A small furniture workshop: four products competing for three shared resources
# plus a contract floor. Chosen so the answer is not "make only the richest
# product" — two resources end up binding and one keeps slack, which is the
# whole point of showing utilisation rather than a single headline number.
PRODUCTS = [
    {"key": "chairs", "margin": 45},
    {"key": "tables", "margin": 80},
    {"key": "desks", "margin": 120},
    {"key": "shelves", "margin": 60},
]

RESOURCES = [
    {
        "key": "machineHours",
        "capacity": 400,
        "usage": {"chairs": 2, "tables": 4, "desks": 6, "shelves": 3},
    },
    {
        "key": "craftHours",
        "capacity": 300,
        "usage": {"chairs": 3, "tables": 5, "desks": 7, "shelves": 2},
    },
    {
        "key": "oakPlanks",
        "capacity": 520,
        "usage": {"chairs": 4, "tables": 9, "desks": 12, "shelves": 6},
    },
]

# A signed contract: at least this many chairs ship, whatever the margin says.
CONTRACT = {"key": "chairContract", "product": "chairs", "minimum": 12}


def solve() -> dict:
    model = Model("workshop")
    model.hideOutput()

    units = {p["key"]: model.addVar(vtype="I", lb=0, name=p["key"]) for p in PRODUCTS}

    rows = []
    for resource in RESOURCES:
        expr = quicksum(resource["usage"][k] * units[k] for k in units)
        model.addCons(expr <= resource["capacity"])
        rows.append(resource)

    model.addCons(units[CONTRACT["product"]] >= CONTRACT["minimum"])

    model.setObjective(quicksum(p["margin"] * units[p["key"]] for p in PRODUCTS), "maximize")
    model.optimize()

    solution = {k: round(model.getVal(v)) for k, v in units.items()}
    objective = round(model.getObjVal(), 2)

    # Utilisation, computed the way exact_analysis does: from x* and the data.
    constraints = []
    for resource in rows:
        activity = sum(resource["usage"][k] * solution[k] for k in solution)
        capacity = resource["capacity"]
        constraints.append(
            {
                "key": resource["key"],
                "activity": activity,
                "capacity": capacity,
                "slack": capacity - activity,
                "utilization": round(activity / capacity * 100, 1),
                "binding": capacity - activity == 0,
                "operator": "<=",
            }
        )

    contract_activity = solution[CONTRACT["product"]]
    constraints.append(
        {
            "key": CONTRACT["key"],
            "activity": contract_activity,
            "capacity": CONTRACT["minimum"],
            "slack": contract_activity - CONTRACT["minimum"],
            "utilization": round(CONTRACT["minimum"] / contract_activity * 100, 1)
            if contract_activity
            else 0.0,
            "binding": contract_activity == CONTRACT["minimum"],
            "operator": ">=",
        }
    )

    # Per-unit draw on each binding resource, so the page can explain WHY the
    # richest product loses with the same numbers the solver used.
    binding_keys = [c["key"] for c in constraints if c["binding"]]
    contributions = [
        {
            "key": p["key"],
            "units": solution[p["key"]],
            "margin": p["margin"],
            "contribution": p["margin"] * solution[p["key"]],
            "share": round(p["margin"] * solution[p["key"]] / objective * 100, 1),
            "usage": {
                r["key"]: r["usage"][p["key"]] for r in RESOURCES if r["key"] in binding_keys
            },
        }
        for p in PRODUCTS
    ]
    # Richest per unit first: the point is that this order is NOT the plan order.
    contributions.sort(key=lambda c: c["margin"], reverse=True)

    return {
        "objective": objective,
        "status": model.getStatus(),
        "constraints": constraints,
        "contributions": contributions,
        "meta": {
            "products": len(PRODUCTS),
            "bindingCount": sum(1 for c in constraints if c["binding"]),
            "totalConstraints": len(constraints),
            "solver": "SCIP",
        },
    }


def emit(data: dict) -> str:
    header = """// AUTO-GENERATED by scripts/gen_landing_analysis.py — do not edit by hand.
//
// A real solve of a small production-planning instance, with the exact analysis
// JAOT computes afterwards: binding constraints, slack, and objective
// contributions derived from x* and the problem data — not shadow prices.
//
// Regenerate with: python scripts/gen_landing_analysis.py

export interface AnalysisConstraint {
  /** Translation key for the constraint's display name. */
  readonly key: string;
  readonly activity: number;
  readonly capacity: number;
  readonly slack: number;
  /** Percent of capacity consumed. */
  readonly utilization: number;
  readonly binding: boolean;
  readonly operator: string;
}

export interface AnalysisContribution {
  readonly key: string;
  readonly units: number;
  readonly margin: number;
  readonly contribution: number;
  /** Percent of the objective this term accounts for. */
  readonly share: number;
  /** Per-unit draw on each binding resource, keyed by constraint key. */
  readonly usage: Readonly<Record<string, number>>;
}

export interface AnalysisShowcase {
  readonly objective: number;
  readonly status: string;
  readonly constraints: readonly AnalysisConstraint[];
  readonly contributions: readonly AnalysisContribution[];
  readonly meta: {
    readonly products: number;
    readonly bindingCount: number;
    readonly totalConstraints: number;
    readonly solver: string;
  };
}

export const ANALYSIS_SHOWCASE: AnalysisShowcase = """
    return header + json.dumps(data, indent=2) + " as const;\n"


def main() -> None:
    data = solve()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(emit(data), encoding="utf-8")

    print(f"Wrote {OUTPUT.relative_to(Path(__file__).resolve().parent.parent)}")
    print(f"  status={data['status']} objective={data['objective']}")
    for c in data["constraints"]:
        flag = "BINDING" if c["binding"] else f"slack {c['slack']}"
        print(
            f"  {c['key']:16s} {c['activity']:6.0f} {c['operator']} {c['capacity']:6.0f} "
            f"({c['utilization']:5.1f}%)  {flag}"
        )
    for t in data["contributions"]:
        print(
            f"  {t['key']:16s} {t['units']:4d} units x {t['margin']:3d} = "
            f"{t['contribution']:7d}  ({t['share']:4.1f}%)"
        )


if __name__ == "__main__":
    main()
