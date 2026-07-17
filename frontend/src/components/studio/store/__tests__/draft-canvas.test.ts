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

  it("derives from model_json when the stored canvas is stale (fewer nodes than vars)", () => {
    // Regression: a non-canvas source (AI Assistant / Editor) replaced the model while
    // the canvas was disabled, leaving a 1-node canvas saved next to a many-variable
    // model. Trusting the canvas rendered the workspace EMPTY (the "0 variables after
    // reload" bug). The richer model_json must win.
    const manyVarModel: OptimizationProblem = {
      variables: Array.from({ length: 6 }, (_, i) => ({
        name: `v${i}`,
        type: "continuous",
        lower_bound: 0,
      })),
      objective: { sense: "minimize", expression: "v0" },
      constraints: [],
    };
    const staleCanvas = { nodes: [{ id: "stale" }], edges: [] };
    const out = resolveDraftCanvas(staleCanvas, manyVarModel);
    expect(out.nodes.length).toBeGreaterThanOrEqual(6); // derived from the 6-var model
    expect(out.nodes.some((n) => (n as { id?: string }).id === "stale")).toBe(false);
  });
});
