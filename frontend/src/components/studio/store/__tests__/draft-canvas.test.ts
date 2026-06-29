import { describe, it, expect } from "vitest";
import { resolveDraftCanvas } from "../draft-canvas";
import type { OptimizationProblem } from "@/lib/types";

const MODEL: OptimizationProblem = {
  variables: [{ name: "x", type: "continuous", lower_bound: 0, upper_bound: 10 }],
  objective: { sense: "minimize", expression: "x" },
  constraints: [{ name: "c1", expression: "x <= 5" }],
};

const EMPTY_MODEL: OptimizationProblem = {
  variables: [],
  objective: { sense: "minimize", expression: "0" },
  constraints: [],
};

describe("resolveDraftCanvas", () => {
  it("uses the stored canvas when it has nodes", () => {
    const canvas = { nodes: [{ id: "n1" }], edges: [{ id: "e1" }] };
    const out = resolveDraftCanvas(canvas, MODEL);
    expect(out.nodes).toHaveLength(1);
    expect(out.nodes[0]).toMatchObject({ id: "n1" });
  });

  it("derives the canvas from model_json when the canvas is empty (API/ERP case)", () => {
    // No canvas, but a real model — must NOT render empty.
    const out = resolveDraftCanvas(null, MODEL);
    expect(out.nodes.length).toBeGreaterThan(0);
  });

  it("derives from model_json when canvas has an empty nodes array", () => {
    const out = resolveDraftCanvas({ nodes: [], edges: [] }, MODEL);
    expect(out.nodes.length).toBeGreaterThan(0);
  });

  it("returns empty when there is neither a canvas nor a real model", () => {
    expect(resolveDraftCanvas(null, EMPTY_MODEL)).toEqual({ nodes: [], edges: [] });
    expect(resolveDraftCanvas(null, null)).toEqual({ nodes: [], edges: [] });
    expect(resolveDraftCanvas({ nodes: [], edges: [] }, EMPTY_MODEL)).toEqual({
      nodes: [],
      edges: [],
    });
  });
});
