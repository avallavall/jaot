import { describe, it, expect } from "vitest";
import { canvasRepresentsModel, resolveDraftCanvas } from "../draft-canvas";
import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
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
  it("uses the stored canvas when, serialized back, it denotes the model", () => {
    // A faithful stored canvas (here: a real derivation with a moved node) is
    // trusted verbatim — that is what preserves user layout across reloads.
    const derived = deserializeFromOptimizationProblem(MODEL);
    derived.nodes[0] = { ...derived.nodes[0], position: { x: 123, y: 456 } };
    const out = resolveDraftCanvas({ nodes: derived.nodes, edges: derived.edges }, MODEL);
    expect(out.nodes[0].position).toEqual({ x: 123, y: 456 });
  });

  it("uses the stored canvas verbatim when there is no model to check against", () => {
    const canvas = { nodes: [{ id: "n1" }], edges: [{ id: "e1" }] };
    const out = resolveDraftCanvas(canvas, EMPTY_MODEL);
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

  it("discards an edge-starved stored canvas and re-derives (regression: prod Treasury)", () => {
    // The old deserializer saved canvases with a node per row but almost no
    // coefficient edges (constraints defaulted to `0 <= 0`). Node count matched
    // the model, so the old count-based guard trusted it — and the studio then
    // hydrated the canonical model from that junk. Serialized-equivalence must
    // reject it and re-derive a canvas that actually denotes the model.
    const model: OptimizationProblem = {
      variables: [
        { name: "cash_1", type: "continuous", lower_bound: 0 },
        { name: "borrow_1", type: "continuous", lower_bound: 0 },
      ],
      objective: { sense: "maximize", expression: "cash_1" },
      constraints: [{ name: "balance_1", expression: "cash_1 == 30000 + borrow_1" }],
    };
    const junk = deserializeFromOptimizationProblem(model);
    const junkCanvas = { nodes: junk.nodes, edges: [] }; // the stored shape: nodes, no edges
    const out = resolveDraftCanvas(junkCanvas, model);
    expect(out.edges.length).toBeGreaterThan(0); // re-derived with its coefficient edges
  });
});

describe("canvasRepresentsModel", () => {
  it("accepts a faithful derivation and rejects a mutated one", () => {
    const canvas = deserializeFromOptimizationProblem(MODEL);
    expect(canvasRepresentsModel(canvas, MODEL)).toBe(true);
    expect(canvasRepresentsModel({ nodes: canvas.nodes, edges: [] }, MODEL)).toBe(false);
    expect(
      canvasRepresentsModel(canvas, {
        ...MODEL,
        variables: [{ name: "x", type: "continuous", lower_bound: 0, upper_bound: 99 }],
      })
    ).toBe(false);
  });
});
