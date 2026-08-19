import { describe, it, expect } from "vitest";

/**
 * The footer read "Powered by SCIP & HiGHS" on every public page. The platform
 * ships four solvers — the studio's own solver matrix offers all four, and the
 * SEO description on the same pages already said "SCIP, HiGHS, CBC and GLPK".
 * These are licence-visible dependencies, and the footer is where a stranger
 * looks to see what the site is built on.
 */

import { SOLVER_CREDITS } from "../Footer";

// CONTRACT-TEST: the footer credits every solver the platform ships
describe("the solvers the footer credits", () => {
  it("names all four", () => {
    expect(SOLVER_CREDITS.map((s) => s.name)).toEqual(["SCIP", "HiGHS", "CBC", "GLPK"]);
  });

  it("links each one to where it lives", () => {
    for (const { href } of SOLVER_CREDITS) {
      expect(href.startsWith("https://")).toBe(true);
    }
    expect(new Set(SOLVER_CREDITS.map((s) => s.href)).size).toBe(SOLVER_CREDITS.length);
  });

  // Hexaly is profile-gated: a public instance does not run it, so crediting it
  // would say the site is built on something it is not.
  it("does not credit the solver a public instance does not run", () => {
    expect(SOLVER_CREDITS.map((s) => s.name)).not.toContain("Hexaly");
  });
});
