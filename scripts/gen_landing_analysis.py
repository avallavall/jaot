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

# A power-electronics plant planning one quarter: seven product families
# competing for the same six plant resources, plus a framework contract.
#
# The instance is tuned (scripts are deterministic; this was searched offline for
# the pattern, then written out) so the answer contradicts the obvious one. The
# margin ranking and the plan disagree completely: the three richest families are
# the heaviest draw on the resources that run out, so the optimum builds none of
# them — while the component everyone assumes is scarce, the microcontrollers,
# finishes the quarter with nearly half its supply untouched.
PRODUCTS = [
    {
        "key": "tractionInverter",
        "margin": 2450,
        "usage": {
            "smtHours": 5,
            "burnInHours": 10,
            "mcuChips": 12,
            "sicModules": 24,
            "testHours": 4,
            "coatingHours": 3,
        },
    },
    {
        "key": "batteryMonitor",
        "margin": 1780,
        "usage": {
            "smtHours": 4,
            "burnInHours": 8,
            "mcuChips": 11,
            "sicModules": 15,
            "testHours": 3,
            "coatingHours": 2,
        },
    },
    {
        "key": "chargeModule",
        "margin": 1320,
        "usage": {
            "smtHours": 4,
            "burnInHours": 5,
            "mcuChips": 9,
            "sicModules": 11,
            "testHours": 3,
            "coatingHours": 2,
        },
    },
    {
        "key": "gridInverter",
        "margin": 960,
        "usage": {
            "smtHours": 3,
            "burnInHours": 3,
            "mcuChips": 8,
            "sicModules": 7,
            "testHours": 2,
            "coatingHours": 2,
        },
    },
    {
        "key": "motorDrive",
        "margin": 740,
        "usage": {
            "smtHours": 3,
            "burnInHours": 2,
            "mcuChips": 7,
            "sicModules": 4,
            "testHours": 2,
            "coatingHours": 1,
        },
    },
    {
        "key": "telemetryUnit",
        "margin": 410,
        "usage": {
            "smtHours": 2,
            "burnInHours": 1,
            "mcuChips": 5,
            "sicModules": 1,
            "testHours": 1,
            "coatingHours": 1,
        },
    },
    {
        "key": "sensorHub",
        "margin": 260,
        "usage": {
            "smtHours": 2,
            "burnInHours": 1,
            "mcuChips": 4,
            "sicModules": 0,
            "testHours": 1,
            "coatingHours": 1,
        },
    },
]

# Quarterly capacity of the plant, in the unit each resource is bought in.
RESOURCES = [
    {"key": "smtHours", "capacity": 58570},
    {"key": "burnInHours", "capacity": 43620},
    {"key": "mcuChips", "capacity": 259580},
    {"key": "sicModules", "capacity": 86040},
    {"key": "testHours", "capacity": 44090},
    {"key": "coatingHours", "capacity": 33160},
]

# A signed framework contract: this many telemetry units ship whatever the
# margin ranking says.
CONTRACT = {"key": "telemetryContract", "product": "telemetryUnit", "minimum": 3500}


def solve() -> dict:
    model = Model("plant-quarter")
    model.hideOutput()

    units = {p["key"]: model.addVar(vtype="I", lb=0, name=p["key"]) for p in PRODUCTS}

    for resource in RESOURCES:
        expr = quicksum(p["usage"][resource["key"]] * units[p["key"]] for p in PRODUCTS)
        model.addCons(expr <= resource["capacity"])

    model.addCons(units[CONTRACT["product"]] >= CONTRACT["minimum"])

    model.setObjective(quicksum(p["margin"] * units[p["key"]] for p in PRODUCTS), "maximize")
    model.optimize()

    assert model.getStatus() == "optimal", model.getStatus()

    solution = {k: round(model.getVal(v)) for k, v in units.items()}
    objective = round(model.getObjVal(), 2)

    # Utilisation, computed the way exact_analysis does: from x* and the data.
    constraints = []
    for resource in RESOURCES:
        activity = sum(p["usage"][resource["key"]] * solution[p["key"]] for p in PRODUCTS)
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

    # The section's argument only works if the richest families lose, so assert
    # it rather than trusting that nobody edited the numbers above.
    ranked = sorted(PRODUCTS, key=lambda p: p["margin"], reverse=True)
    # The headline says "the three highest-margin products never make the plan".
    assert all(solution[p["key"]] == 0 for p in ranked[:3]), (
        "the three richest families must not make the plan"
    )
    binding_keys = [c["key"] for c in constraints if c["binding"]]
    assert len(binding_keys) >= 2, "at least two limits must run out"
    # The section says the richest family is the heaviest draw on every limit
    # that ran out. Keep that claim true or fail the regeneration.
    for key in binding_keys:
        assert ranked[0]["usage"][key] == max(p["usage"][key] for p in PRODUCTS), (
            f"the richest family must be the heaviest draw on {key}"
        )

    # Per-unit draw on each binding resource, so the page can explain WHY the
    # richest family loses with the same numbers the solver used.
    contributions = [
        {
            "key": p["key"],
            "units": solution[p["key"]],
            "margin": p["margin"],
            "contribution": p["margin"] * solution[p["key"]],
            "share": round(p["margin"] * solution[p["key"]] / objective * 100, 1),
            "usage": {r: p["usage"][r] for r in binding_keys if r in p["usage"]},
        }
        for p in ranked
    ]

    # The loosest limit, named: the point that buying more of it changes nothing
    # is as useful as knowing what binds, and it is the counterintuitive half.
    loosest = min(
        (c for c in constraints if c["operator"] == "<=" and not c["binding"]),
        key=lambda c: c["utilization"],
    )

    return {
        "objective": objective,
        "status": "optimal",
        "constraints": constraints,
        "contributions": contributions,
        "loosest": {"key": loosest["key"], "slack": loosest["slack"]},
        "meta": {
            "products": len(PRODUCTS),
            "unitsBuilt": sum(solution.values()),
            "bindingCount": len(binding_keys),
            "totalConstraints": len(constraints),
            "nodes": model.getNNodes(),
            "solver": "SCIP",
        },
    }


def emit(data: dict) -> str:
    header = """// AUTO-GENERATED by scripts/gen_landing_analysis.py — do not edit by hand.
//
// A real solve of a quarterly production plan for a power-electronics plant,
// with the exact analysis JAOT computes afterwards: binding constraints, slack,
// and objective contributions derived from x* and the problem data — not shadow
// prices.
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
  /** The capacity limit furthest from running out, and by how much. */
  readonly loosest: {
    readonly key: string;
    readonly slack: number;
  };
  readonly meta: {
    readonly products: number;
    readonly unitsBuilt: number;
    readonly bindingCount: number;
    readonly totalConstraints: number;
    readonly nodes: number;
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
    print(
        f"  status={data['status']} objective={data['objective']:,.0f} nodes={data['meta']['nodes']}"
    )
    for c in data["constraints"]:
        flag = "BINDING" if c["binding"] else f"slack {c['slack']:,}"
        print(
            f"  {c['key']:18s} {c['activity']:9,d} {c['operator']} {c['capacity']:9,d} "
            f"({c['utilization']:5.1f}%)  {flag}"
        )
    for t in data["contributions"]:
        print(
            f"  {t['key']:18s} {t['units']:8,d} units x {t['margin']:5d} = "
            f"{t['contribution']:12,d}  ({t['share']:4.1f}%)"
        )
    print(f"  loosest: {data['loosest']['key']} with {data['loosest']['slack']:,} spare")


if __name__ == "__main__":
    main()
