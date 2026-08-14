import { describe, expect, it } from "vitest";

import {
  solverDescription,
  solverDisplayName,
} from "@/lib/solver-display";

/** A stand-in for next-intl's translator with a fixed set of known keys. */
function translator(known: Record<string, string>) {
  const t = (key: string) => known[key] ?? key;
  t.has = (key: string) => key in known;
  return t;
}

describe("solverDisplayName", () => {
  it("renders each shipped solver with its own capitalisation", () => {
    expect(solverDisplayName("scip")).toBe("SCIP");
    expect(solverDisplayName("highs")).toBe("HiGHS");
    expect(solverDisplayName("cbc")).toBe("CBC");
    expect(solverDisplayName("glpk")).toBe("GLPK");
    expect(solverDisplayName("hexaly")).toBe("Hexaly");
  });

  it("uppercases a solver it has never heard of", () => {
    expect(solverDisplayName("gurobi")).toBe("GUROBI");
  });
});

describe("solverDescription", () => {
  it("prefers the translation over the English line the API sends", () => {
    const t = translator({ "glpk.description": "Solver LP/MIP de GNU, de un solo hilo" });

    expect(solverDescription("glpk", "GNU LP/MIP solver, single-threaded", t)).toBe(
      "Solver LP/MIP de GNU, de un solo hilo",
    );
  });

  it("falls back to the API description when no translation exists", () => {
    // A solver added on the backend must stay visible in the picker before the
    // messages catch up, in English rather than with a blank line.
    const t = translator({});

    expect(solverDescription("xpress", "Commercial LP/MIP", t)).toBe("Commercial LP/MIP");
  });

  it("returns nothing when neither side has anything to say", () => {
    expect(solverDescription("xpress", undefined, translator({}))).toBeUndefined();
  });
});
