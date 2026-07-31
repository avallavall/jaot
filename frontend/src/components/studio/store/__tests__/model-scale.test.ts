import { describe, it, expect } from "vitest";
import {
  CANVAS_SCALE_CAP,
  canvasCanRepresentModel,
  exceedsCanvasScale,
  modelElementCount,
} from "../model-scale";
import { resolveDraftCanvas } from "../draft-canvas";
import type { OptimizationProblem } from "@/lib/types";

function problemWith(varCount: number, constraintCount = 0): OptimizationProblem {
  return {
    variables: Array.from({ length: varCount }, (_, i) => ({
      name: `x${i}`,
      type: "binary" as const,
    })),
    objective: { sense: "minimize", expression: "0" },
    constraints: Array.from({ length: constraintCount }, (_, i) => ({
      name: `c${i}`,
      expression: `x${i} <= 1`,
    })),
  };
}

describe("model-scale — the visual-canvas hairball guard", () => {
  it("counts variables + constraints", () => {
    expect(modelElementCount(problemWith(10, 5))).toBe(15);
    expect(modelElementCount(null)).toBe(0);
  });

  it("flags a model just over the cap and clears one at the cap", () => {
    expect(exceedsCanvasScale(problemWith(CANVAS_SCALE_CAP))).toBe(false);
    expect(exceedsCanvasScale(problemWith(CANVAS_SCALE_CAP + 1))).toBe(true);
  });

  it("an imported large MILP (e.g. a 200×200 assignment) is over the cap", () => {
    // ~40k binary vars — deriving this many nodes is what froze the tab.
    expect(exceedsCanvasScale(problemWith(40_000, 400))).toBe(true);
  });
});

describe("resolveDraftCanvas never deserializes a too-large model", () => {
  it("returns an empty canvas instead of laying out tens of thousands of nodes", () => {
    const huge = problemWith(CANVAS_SCALE_CAP + 5000);
    const { nodes, edges } = resolveDraftCanvas(null, huge);
    expect(nodes).toEqual([]);
    expect(edges).toEqual([]);
  });

  it("still derives a canvas for a model within the cap", () => {
    const small = problemWith(3, 1);
    const { nodes } = resolveDraftCanvas(null, small);
    expect(nodes.length).toBeGreaterThan(0);
  });
});

describe("canvasCanRepresentModel — the canvas representability guard", () => {
  const base: OptimizationProblem = {
    variables: [
      { name: "x", type: "continuous", lower_bound: 0 },
      { name: "y", type: "continuous", lower_bound: 0 },
    ],
    objective: { sense: "minimize", expression: "x + 2*y" },
    constraints: [{ name: "c", expression: "x == y + 4" }],
  };

  it("accepts a general linear model (variables on both sides, constants folded)", () => {
    expect(canvasCanRepresentModel(base)).toBe(true);
  });

  it("rejects nonlinear constraints", () => {
    expect(
      canvasCanRepresentModel({
        ...base,
        constraints: [{ name: "nl", expression: "x * y <= 5" }],
      })
    ).toBe(false);
  });

  it("rejects an objective constant (no edge can carry it)", () => {
    expect(
      canvasCanRepresentModel({
        ...base,
        objective: { sense: "minimize", expression: "x + 5" },
      })
    ).toBe(false);
  });

  it("rejects a term over an undeclared variable", () => {
    expect(
      canvasCanRepresentModel({
        ...base,
        constraints: [{ name: "ghost", expression: "x + ghost <= 5" }],
      })
    ).toBe(false);
  });
});
