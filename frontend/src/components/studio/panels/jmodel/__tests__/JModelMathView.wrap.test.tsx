/**
 * Long formulas wrap inside the JModel math pane.
 *
 * KaTeX's display mode sets `white-space: nowrap`, so a derived draft's
 * objective (dozens of terms) ran past the pane's right edge and was cut
 * there (browser QA, 2026-09-24). KaTeX already splits a formula into pieces
 * after each relation and binary operator; the pane lets the line break there.
 *
 * jsdom has no layout, so this checks the two halves that make the wrap: the
 * rendered formulas sit inside the class, and the stylesheet gives that class
 * the rule. Measured in Chromium: a 1,169 px objective in a 528 px pane went
 * from clipped to three lines with no horizontal overflow.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { JModelMathView } from "../JModelMathView";

vi.mock("@/lib/api", () => ({
  api: {
    latexDsl: vi.fn().mockResolvedValue({
      ok: true,
      model: {
        objective: {
          latex:
            "\\min \\quad 80000\\,open_{madrid} + 90000\\,open_{barcelona} + 60000\\,open_{valencia}",
          label: "obj",
        },
        constraints: [{ latex: "x_{1} + x_{2} + x_{3} \\le 1", label: "c1" }],
        variables: [{ latex: "x_{i} \\in \\{0, 1\\}", label: "x" }],
      },
    }),
  },
}));

const GLOBALS_CSS = path.resolve(__dirname, "../../../../../app/globals.css");

describe("the JModel math pane", () => {
  it("renders every formula inside the class that lets it wrap", async () => {
    const { container } = render(<JModelMathView source="minimize obj: x;" active />);
    await screen.findByText("studio.jmodelMathObjective");

    const formulas = container.querySelectorAll(".katex-display");
    expect(formulas.length).toBe(3);
    for (const formula of formulas) {
      expect(formula.closest(".jmodel-math-lines")).not.toBeNull();
    }
  });

  it("has a stylesheet rule that lifts KaTeX's nowrap for that class", () => {
    const css = fs.readFileSync(GLOBALS_CSS, "utf8");
    const rule = css.match(/\.jmodel-math-lines \.katex-display > \.katex\s*\{([^}]*)\}/);
    expect(rule).not.toBeNull();
    expect(rule![1]).toMatch(/white-space:\s*normal/);
  });
});
