import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

// Many places printed a solver key in capitals ("HIGHS") where the brand is
// "HiGHS": the matrix, the model's runs and scenarios, and the comparer's notes
// and work chart. `solverDisplayName` is the one way to print a solver.
const SRC = path.resolve(__dirname, "../..");
const UPPERCASED_SOLVER = new RegExp(
  [
    /\bsolver(?:_name|Name)?\??\.toUpperCase\(\)/.source,
    // A CSS capitals class around a raw solver field ("HIGHS" on screen).
    /uppercase[^"]*">\s*\{\w+\.(?:name|solver|solver_name)\}/.source,
    // Chart axes and tooltips that upper-case the solver key.
    /tickFormatter=\{\(name: string\) => name\.toUpperCase\(\)\}/.source,
    /String\(label\)\.toUpperCase\(\)/.source,
  ].join("|"),
);

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "__tests__" ? [] : sources(full);
    return /\.(ts|tsx)$/.test(entry.name) && !entry.name.includes(".test.") ? [full] : [];
  });
}

describe("solver names", () => {
  it("are printed with solverDisplayName, never upper-cased by hand", () => {
    const offenders = sources(SRC)
      .filter((file) => !file.endsWith("solver-display.ts"))
      .filter((file) => UPPERCASED_SOLVER.test(fs.readFileSync(file, "utf8")))
      .map((file) => path.relative(SRC, file));
    expect(offenders).toEqual([]);
  });
});
