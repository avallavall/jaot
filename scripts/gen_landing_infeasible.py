"""Generate the landing page's infeasibility showcase with the real solver.

When a model has no answer, a solver says "infeasible" and stops. JAOT finds an
Irreducible Infeasible Set: a minimal group of rules that contradict each other,
where dropping any one of them makes the model solvable again. This script
reproduces that with the same method the product uses — deletion filtering, one
feasibility re-solve per removable constraint, objective replaced by the constant
0 so a candidate can only come back feasible or infeasible, never unbounded
(app/domains/solver/services/infeasibility.py).

Same plant as the analysis section, so the page tells one story: a customer wants
a quarter's worth of traction inverters and the line cannot carry it. Exactly one
of the six capacity limits falls short, which is the point — five of them are
cleared by name instead of being left under suspicion.

The instance is written out by hand and the search is exhaustive, so the result
is deterministic.

    python scripts/gen_landing_infeasible.py

Output: frontend/src/components/landing/data/infeasibleShowcase.ts
"""

from __future__ import annotations

import json
from pathlib import Path

from pyscipopt import Model

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "src"
    / "components"
    / "landing"
    / "data"
    / "infeasibleShowcase.ts"
)

# One product line, seven rules. The contract asks for 6,000 traction inverters
# this quarter; every limit reaches it except burn-in, which stops at 5,240.
# The per-unit coefficients are the traction inverter's row from
# gen_landing_analysis.py, so both sections describe the same plant.
DEMAND = 6000
RULES = [
    {"key": "inverterContract", "coefficient": 1, "operator": ">=", "rhs": DEMAND},
    {"key": "smtHours", "coefficient": 5, "operator": "<=", "rhs": 38500},
    {"key": "burnInHours", "coefficient": 10, "operator": "<=", "rhs": 52400},
    {"key": "mcuChips", "coefficient": 12, "operator": "<=", "rhs": 94800},
    {"key": "sicModules", "coefficient": 24, "operator": "<=", "rhs": 158400},
    {"key": "testHours", "coefficient": 4, "operator": "<=", "rhs": 27600},
    {"key": "coatingHours", "coefficient": 3, "operator": "<=", "rhs": 19800},
]


def is_feasible(active: list[dict]) -> bool:
    """Solve a pure feasibility problem over the given rules."""
    model = Model("feasibility")
    model.hideOutput()
    inverters = model.addVar(vtype="I", lb=0, name="inverters")
    for rule in active:
        if rule["operator"] == ">=":
            model.addCons(rule["coefficient"] * inverters >= rule["rhs"])
        else:
            model.addCons(rule["coefficient"] * inverters <= rule["rhs"])
    # Constant objective: the answer can only be feasible or infeasible.
    model.setObjective(0)
    model.optimize()
    return model.getStatus() != "infeasible"


def deletion_filter() -> list[str]:
    """Deletion filtering, as the product does it: tentatively drop each rule and
    keep it only if the model becomes feasible without it."""
    required = list(RULES)
    for rule in list(required):
        candidate = [r for r in required if r["key"] != rule["key"]]
        if not is_feasible(candidate):
            # Still contradictory without it — the rule was not part of the clash.
            required = candidate
    return [r["key"] for r in required]


def build() -> dict:
    assert not is_feasible(RULES), "the showcase instance must be infeasible"

    conflict = deletion_filter()
    assert is_feasible([r for r in RULES if r["key"] != conflict[0]]), (
        "dropping a member of the conflict must restore feasibility"
    )

    rows = []
    for rule in RULES:
        # What this rule alone would allow, in units of the product.
        limit = rule["rhs"] / rule["coefficient"]
        rows.append(
            {
                "key": rule["key"],
                "operator": rule["operator"],
                "rhs": rule["rhs"],
                "coefficient": rule["coefficient"],
                "allows": int(limit),
                "inConflict": rule["key"] in conflict,
            }
        )

    # Exactly one ceiling may fall short. If a second one did, the section's
    # claim that the others are cleared would read as wrong against its own bars.
    short = [r for r in rows if r["operator"] == "<=" and r["allows"] < DEMAND]
    assert len(short) == 1, f"expected one short limit, got {[r['key'] for r in short]}"

    # The actionable number: how much more of the binding resource the demand needs.
    tightest = short[0]
    shortfall = DEMAND * tightest["coefficient"] - tightest["rhs"]

    return {
        "demand": DEMAND,
        "rules": rows,
        "conflict": conflict,
        "shortfall": {
            "resource": tightest["key"],
            "missing": shortfall,
            "reaches": tightest["allows"],
        },
        "meta": {
            "totalRules": len(RULES),
            "conflictSize": len(conflict),
            "clearedCount": len(RULES) - len(conflict),
            "method": "deletion filtering",
            "solver": "SCIP",
        },
    }


def emit(data: dict) -> str:
    header = """// AUTO-GENERATED by scripts/gen_landing_infeasible.py — do not edit by hand.
//
// A genuinely infeasible instance, reduced to its irreducible infeasible set by
// the same deletion filtering the product uses. Every rule below was tested by
// re-solving without it.
//
// Regenerate with: python scripts/gen_landing_infeasible.py

export interface InfeasibleRule {
  readonly key: string;
  readonly operator: string;
  readonly rhs: number;
  readonly coefficient: number;
  /** Units of the product this rule alone would permit. */
  readonly allows: number;
  /** Whether the rule belongs to the irreducible infeasible set. */
  readonly inConflict: boolean;
}

export interface InfeasibleShowcase {
  readonly demand: number;
  readonly rules: readonly InfeasibleRule[];
  readonly conflict: readonly string[];
  readonly shortfall: {
    readonly resource: string;
    readonly missing: number;
    readonly reaches: number;
  };
  readonly meta: {
    readonly totalRules: number;
    readonly conflictSize: number;
    readonly clearedCount: number;
    readonly method: string;
    readonly solver: string;
  };
}

export const INFEASIBLE_SHOWCASE: InfeasibleShowcase = """
    return header + json.dumps(data, indent=2) + " as const;\n"


def main() -> None:
    data = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(emit(data), encoding="utf-8")

    print(f"Wrote {OUTPUT.relative_to(Path(__file__).resolve().parent.parent)}")
    print(f"  demand={data['demand']:,}  conflict={data['conflict']}")
    for r in data["rules"]:
        mark = "CONFLICT" if r["inConflict"] else "cleared"
        print(
            f"  {r['key']:18s} {r['coefficient']:3d}x {r['operator']} {r['rhs']:8,d} "
            f"-> allows {r['allows']:6,d}   {mark}"
        )
    s = data["shortfall"]
    print(f"  shortfall: {s['missing']:,} more {s['resource']} (reaches {s['reaches']:,})")


if __name__ == "__main__":
    main()
