import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  solverColor,
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
    expect(solverDisplayName("jaos")).toBe("JAOS");
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

/**
 * Charts took the five-colour palette by position, so JAOS, the fifth solver,
 * was dark brown on the dark theme and GLPK pale beige on the light one. Every
 * solver has its own colour now, defined for both themes.
 */
describe("solverColor", () => {
  const SOLVERS = ["scip", "highs", "cbc", "glpk", "jaos"];

  it("gives every solver its own colour, whatever its position", () => {
    const colours = SOLVERS.map((s, i) => solverColor(s, i));
    expect(new Set(colours).size).toBe(SOLVERS.length);
    expect(solverColor("jaos", 4)).toBe(solverColor("JAOS", 0));
  });

  it("has a colour for each solver in the light and the dark theme", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../../app/globals.css"), "utf8");
    const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));
    const dark = css.slice(css.indexOf(".dark {"), css.indexOf("}", css.indexOf(".dark {")));
    for (const s of [...SOLVERS, "hexaly"]) {
      expect(root).toContain(`--solver-${s}:`);
      expect(dark).toContain(`--solver-${s}:`);
    }
  });

  it("falls back to the chart palette for a solver it does not know", () => {
    expect(solverColor("gurobi", 6)).toBe("var(--chart-2)");
  });
});
