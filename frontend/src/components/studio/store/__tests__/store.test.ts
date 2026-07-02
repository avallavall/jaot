import { describe, it, expect } from "vitest";
import { createModelProjectStore, selectHasParseError } from "../createModelProjectStore";
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
  it("records the editing source and marks the draft dirty", () => {
    const store = makeStore();
    const next: OptimizationProblem = {
      ...BASE,
      constraints: [{ name: "c1", expression: "x + y <= 8" }],
    };
    store.getState().setProblem(next, { source: "canvas" });
    const s = store.getState();
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

describe("ModelProjectStore.setProblem — canvas hairball guard", () => {
  const big = (n: number): OptimizationProblem => ({
    variables: Array.from({ length: n }, (_, i) => ({
      name: `v${i}`,
      type: "continuous",
      lower_bound: 0,
    })),
    objective: { sense: "minimize", expression: "v0" },
    constraints: [],
  });

  it("re-enables the canvas when a non-canvas source shrinks a large model", () => {
    // The data-loss regression: loaded large (canvas disabled), the Assistant then
    // replaces it with a small model — the canvas must come back so it lays out and
    // autosave persists a canvas that matches the new model.
    const store = createModelProjectStore({ modelId: "m", name: "M", problem: big(900) });
    store.getState().setCanvasDisabled(true);
    store.getState().setProblem(big(10), { source: "formulation" });
    expect(store.getState().canvasDisabled).toBe(false);
  });

  it("disables the canvas when a non-canvas source grows past the cap", () => {
    const store = makeStore();
    expect(store.getState().canvasDisabled).toBe(false);
    store.getState().setProblem(big(900), { source: "formulation" });
    expect(store.getState().canvasDisabled).toBe(true);
  });

  it("leaves the flag untouched for a canvas-sourced edit", () => {
    const store = makeStore();
    store.getState().setCanvasDisabled(true);
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "canvas" });
    expect(store.getState().canvasDisabled).toBe(true);
  });
});

describe("ModelProjectStore.parseErrors (per-lens, fold of the old two booleans)", () => {
  it("defaults empty; selectHasParseError is false until a lens reports one", () => {
    const store = makeStore();
    expect(store.getState().parseErrors).toEqual({});
    expect(selectHasParseError(store.getState())).toBe(false);
    store.getState().setParseError("scratch", true);
    expect(selectHasParseError(store.getState())).toBe(true);
  });

  it("clearing a lens removes its key (no lingering false entry)", () => {
    const store = makeStore();
    store.getState().setParseError("scratch", true);
    store.getState().setParseError("scratch", false);
    expect(store.getState().parseErrors).toEqual({});
    expect(selectHasParseError(store.getState())).toBe(false);
  });

  it("tracks the two authoring lenses independently (no cross-block)", () => {
    const store = makeStore();
    store.getState().setParseError("scratch", true);
    store.getState().setParseError("dsl", true);
    expect(selectHasParseError(store.getState())).toBe(true);
    store.getState().setParseError("scratch", false);
    // dsl still broken => still blocked
    expect(selectHasParseError(store.getState())).toBe(true);
    expect(store.getState().parseErrors.dsl).toBe(true);
  });

  it("a change from another source clears a stale lens error", () => {
    const store = makeStore();
    store.getState().setParseError("scratch", true);
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "canvas" });
    expect(selectHasParseError(store.getState())).toBe(false);
  });

  it("survives a same-source change (the lens owns its own block)", () => {
    const store = makeStore();
    store.getState().setParseError("scratch", true);
    // A scratch edit that applies a valid problem clears the flag explicitly in the
    // panel; setProblem itself must NOT clear the SOURCE lens' error.
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "scratch" });
    expect(store.getState().parseErrors.scratch).toBe(true);
  });

  it("is cleared on hydrate (reload / restore)", () => {
    const store = makeStore();
    store.getState().setParseError("scratch", true);
    store.getState().setParseError("dsl", true);
    store.getState().hydrate(BASE, "Reloaded");
    expect(store.getState().parseErrors).toEqual({});
  });
});

describe("ModelProjectStore JModel (DSL) source", () => {
  it("setDraftDslSource without dirty does not mark the draft dirty (load-time rehydrate)", () => {
    const store = makeStore();
    store.getState().setDraftDslSource("set I := {a};");
    expect(store.getState().draftDslSource).toBe("set I := {a};");
    expect(store.getState().headDirty).toBe(false);
  });

  it("setDraftDslSource with dirty marks the draft (and the DSL) dirty → autosave", () => {
    const store = makeStore();
    store.getState().setDraftDslSource("var x >= 0;", { dirty: true });
    expect(store.getState().headDirty).toBe(true);
    expect(store.getState().dslDirty).toBe(true);
  });

  it("dslDirty gates persistence: false after a rehydrate, true after a user edit", () => {
    const store = makeStore();
    // Rehydrate (load) sets the source without dirtying — autosave must not fire.
    store.getState().setDraftDslSource("set I := {a};");
    expect(store.getState().dslDirty).toBe(false);
    // Once the user edits, the empty string must be persistable (a delete sticks).
    store.getState().setDraftDslSource("var x >= 0;", { dirty: true });
    expect(store.getState().dslDirty).toBe(true);
    store.getState().setDraftDslSource("", { dirty: true });
    expect(store.getState().draftDslSource).toBe("");
    expect(store.getState().dslDirty).toBe(true);
  });

  it("a non-dsl source change clears a stale dsl error but a dsl change keeps it", () => {
    const store = makeStore();
    store.getState().setParseError("dsl", true);
    // A canvas edit moots a stale JModel error.
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "canvas" });
    expect(store.getState().parseErrors.dsl ?? false).toBe(false);

    // A dsl-sourced change does NOT self-clear (the panel owns its block), and it
    // does clear a stale editor error.
    store.getState().setParseError("scratch", true);
    store.getState().setParseError("dsl", true);
    store.getState().setProblem({ ...BASE, constraints: [{ name: "c", expression: "x <= 1" }] }, {
      source: "dsl",
    });
    expect(store.getState().parseErrors.dsl).toBe(true);
    expect(store.getState().parseErrors.scratch ?? false).toBe(false);
  });

  it("records dsl as the source on a dsl-sourced change", () => {
    const store = makeStore();
    store.getState().setProblem({ ...BASE, constraints: [] }, { source: "dsl" });
    expect(store.getState().lastSource).toBe("dsl");
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
