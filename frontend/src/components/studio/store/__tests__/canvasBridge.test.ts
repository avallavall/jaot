import { describe, it, expect } from "vitest";
import { reattachVariableStructure } from "../useCanvasBridge";
import { problemsEqual } from "../createModelProjectStore";
import type { OptimizationProblem } from "@/lib/types";

type Variable = OptimizationProblem["variables"][number];

// Regression guard for the A1 × canvas-bridge interaction: A1 added server-derived
// `family`/`index_tuple` to each Variable. The canvas nodes can't store them, so a
// reprojection of an UNTOUCHED canvas dropped them — and because the store's equality
// guard is a full JSON compare (`problemsEqual`), the dropped fields fired a phantom
// `setProblem(source:"canvas")` that drifted the DSL/editor source to read-only just from
// viewing the canvas. `reattachVariableStructure` re-attaches the fields by name.

const dslVars: Variable[] = [
  {
    name: "x_a",
    type: "binary",
    lower_bound: 0,
    upper_bound: 1,
    family: "x",
    index_tuple: ["a"],
  },
  {
    name: "x_b",
    type: "binary",
    lower_bound: 0,
    upper_bound: 1,
    family: "x",
    index_tuple: ["b"],
  },
] as Variable[];

// What the canvas round-trip produces: the same variables minus the fields it cannot
// represent (identical key order otherwise, which is what kept it JSON-equal pre-A1).
const canvasVars: Variable[] = [
  { name: "x_a", type: "binary", lower_bound: 0, upper_bound: 1 },
  { name: "x_b", type: "binary", lower_bound: 0, upper_bound: 1 },
] as Variable[];

describe("reattachVariableStructure (canvas bridge idempotency, A1 regression guard)", () => {
  it("re-attaches family/index_tuple by name → a reprojected untouched canvas is byte-identical", () => {
    const merged = reattachVariableStructure(canvasVars, dslVars);
    expect(JSON.stringify(merged)).toBe(JSON.stringify(dslVars));
  });

  it("makes the reprojected problem problemsEqual to the canonical one (no phantom drift)", () => {
    const problem = {
      name: "m",
      variables: dslVars,
      objective: { sense: "maximize", expression: "x_a + x_b" },
      constraints: [{ name: "c", expression: "x_a + x_b <= 1" }],
    } as unknown as OptimizationProblem;
    const reprojected = {
      ...problem,
      variables: reattachVariableStructure(canvasVars, problem.variables),
    } as OptimizationProblem;
    // Before the fix this was false → setProblem fired → lastSource drifted to "canvas".
    expect(problemsEqual(reprojected, problem)).toBe(true);
  });

  it("keeps no structure for a genuinely new canvas variable (a hand-drawn var has no family)", () => {
    const newVar: Variable[] = [
      { name: "y_new", type: "continuous", lower_bound: 0, upper_bound: 10 },
    ] as Variable[];
    const merged = reattachVariableStructure(newVar, dslVars);
    expect(merged[0].family ?? null).toBeNull();
    expect(merged[0].index_tuple ?? null).toBeNull();
  });
});
