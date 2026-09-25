import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// The shared setup mocks next-intl/server without getFormatter.
vi.mock("next-intl/server", () => ({
  getTranslations: async (ns: string) =>
    Object.assign((key: string) => `${ns}.${key}`, { has: () => true }),
  getFormatter: async () => ({
    number: (v: number) => String(v),
    list: (items: string[]) => items.join(", "),
  }),
}));

import { SolverRaceShowcase } from "../SolverRaceShowcase";

/**
 * JAOS has to appear wherever the other solvers do (owner, 2026-09-25). The
 * home race also printed the solver key in capitals, "HIGHS".
 */
describe("the home page solver race", () => {
  it("shows all five solvers by their brand names", async () => {
    render(await SolverRaceShowcase());
    for (const name of ["SCIP", "HiGHS", "CBC", "GLPK", "JAOS"]) {
      expect(screen.getByText(name, { selector: "span" })).toBeInTheDocument();
    }
    expect(screen.queryByText("HIGHS")).toBeNull();
  });
});
