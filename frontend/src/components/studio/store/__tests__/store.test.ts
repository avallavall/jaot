import { describe, it, expect } from "vitest";
import { createModelProjectStore } from "../createModelProjectStore";
import { selectModelStats } from "../stats";
import type { OptimizationProblem } from "@/lib/types";

const BASE: OptimizationProblem = {
  variables: [
    { name: "x", type: "continuous", lower_bound: 0 },
    { name: "y", type: "integer", lower_bound: 0 },
  ],
  objective: { sense: "maximize", expression: "3*x + 2*y" },
  constraints: [{ name: "c1", expression: "x + y <= 4" }],
};

function makeStore() {
  return createModelProjectStore({ modelId: "bld_test", name: "Test", problem: BASE });
}

describe("ModelProjectStore.setProblem", () => {
  it("makes the editing rep canonical and marks the others dirty", () => {
    const store = makeStore();
    const next: OptimizationProblem = {
      ...BASE,
      constraints: [{ name: "c1", expression: "x + y <= 8" }],
    };
    store.getState().setProblem(next, { source: "canvas" });
    const s = store.getState();
    expect(s.repStatus.canvas).toBe("synced");
    expect(s.repStatus.scratch).toBe("dirty");
    expect(s.repStatus.formulation).toBe("dirty");
    expect(s.headDirty).toBe(true);
    expect(s.lastSource).toBe("canvas");
    expect(s.problem.constraints[0].expression).toContain("<= 8");
  });

  it("is idempotent — an identical model is a no-op (the loop/autosave guard)", () => {
    const store = makeStore();
    const same: OptimizationProblem = JSON.parse(JSON.stringify(BASE));
    store.getState().setProblem(same, { source: "canvas" });
    const s = store.getState();
    // No change => not dirty => no autosave, and the bridge cannot ping-pong.
    expect(s.headDirty).toBe(false);
    expect(s.lastSource).toBeNull();
    expect(s.repStatus.scratch).toBe("synced");
  });

  it("hydrate replaces the model without marking it dirty", () => {
    const store = makeStore();
    store.getState().setProblem(
      { ...BASE, constraints: [] },
      { source: "canvas" }
    );
    expect(store.getState().headDirty).toBe(true);
    store.getState().hydrate(BASE, "Reloaded");
    const s = store.getState();
    expect(s.headDirty).toBe(false);
    expect(s.name).toBe("Reloaded");
    expect(s.problem.constraints).toHaveLength(1);
  });
});

describe("ModelProjectStore.editorParseError", () => {
  it("defaults to false and toggles via the setter", () => {
    const store = makeStore();
    expect(store.getState().editorParseError).toBe(false);
    store.getState().setEditorParseError(true);
    expect(store.getState().editorParseError).toBe(true);
  });

  it("is cleared when the model changes from a non-scratch source", () => {
    const store = makeStore();
    store.getState().setEditorParseError(true);
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "canvas" });
    expect(store.getState().editorParseError).toBe(false);
  });

  it("survives a scratch-sourced change (the editor owns its own block)", () => {
    const store = makeStore();
    store.getState().setEditorParseError(true);
    // A scratch edit that applies a valid problem clears the flag explicitly in the
    // panel; setProblem itself must NOT clear it for scratch (the panel is in charge).
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "scratch" });
    expect(store.getState().editorParseError).toBe(true);
  });

  it("is cleared on hydrate (reload / restore)", () => {
    const store = makeStore();
    store.getState().setEditorParseError(true);
    store.getState().hydrate(BASE, "Reloaded");
    expect(store.getState().editorParseError).toBe(false);
  });
});

describe("selectModelStats", () => {
  it("classifies a mixed model and counts structure", () => {
    const stats = selectModelStats(BASE);
    expect(stats.varTotal).toBe(2);
    expect(stats.varInteger).toBe(1);
    expect(stats.varContinuous).toBe(1);
    expect(stats.constraintTotal).toBe(1);
    expect(stats.problemClass).toBe("MILP");
    expect(stats.nonzeros).toBe(2);
  });

  it("classifies a pure-continuous model as LP", () => {
    const lp: OptimizationProblem = {
      variables: [{ name: "x", type: "continuous", lower_bound: 0 }],
      objective: { sense: "minimize", expression: "x" },
      constraints: [],
    };
    expect(selectModelStats(lp).problemClass).toBe("LP");
  });
});
