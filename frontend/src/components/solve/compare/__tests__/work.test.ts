import { describe, expect, it } from "vitest";

import type { ComparisonSolverResult, ProgressTracePoint } from "@/lib/types";

import { cumulativeWork, withFinalCount, workData, workOf } from "../work";

function point(seconds: number, node: number | null): ProgressTracePoint {
  return {
    iteration: 1,
    node,
    objective: 10,
    primal_bound: 10,
    dual_bound: 9,
    gap: 0.1,
    elapsed_seconds: seconds,
  };
}

function solver(
  name: string,
  overrides: Partial<ComparisonSolverResult> = {},
): ComparisonSolverResult {
  return {
    solver_name: name,
    execution_id: `exe_${name}`,
    status: "completed",
    solver_status: "optimal",
    unsupported_reason: null,
    objective_value: 10,
    dual_bound: 10,
    gap: 0,
    iterations: 800,
    nodes: 200,
    wall_time_ms: 2000,
    solver_time_seconds: 2,
    error_message: null,
    progress_history: null,
    ...overrides,
  };
}

describe("workOf", () => {
  it("counts the tree when the solver searched one", () => {
    expect(workOf(solver("scip"))).toEqual({ unit: "nodes", total: 200 });
  });

  it("falls back to iterations when there is no tree", () => {
    expect(workOf(solver("highs", { nodes: 0 }))).toEqual({ unit: "iterations", total: 800 });
    expect(workOf(solver("highs", { nodes: null }))).toEqual({ unit: "iterations", total: 800 });
  });

  it("has nothing to draw when the solver counted neither", () => {
    expect(workOf(solver("glpk", { nodes: null, iterations: null }))).toBeNull();
    expect(workOf(solver("glpk", { nodes: 0, iterations: 0 }))).toBeNull();
  });
});

describe("cumulativeWork", () => {
  // CONTRACT-TEST: CBC counts nodes from zero again on every restart, mid-run.
  // These are the numbers from a real `cbc -log 2` trace on a knapsack this
  // project generated: 150 nodes at 0.15 s, then 0 nodes at 0.16 s, and CBC's
  // own summary line says the search took 200 nodes. Drawn as reported the line
  // saws back to the floor and ends at 50, a quarter of what the table shows.
  it("carries the total forward when CBC restarts its count", () => {
    const trace = [point(0.04, 50), point(0.09, 100), point(0.15, 150), point(0.16, 0), point(0.22, 50)];
    expect(cumulativeWork(trace).map((p) => p.work)).toEqual([50, 100, 150, 150, 200]);
  });

  it("leaves a trace that never restarts untouched", () => {
    const trace = [point(0.1, 10), point(0.2, 40), point(0.3, 90)];
    expect(cumulativeWork(trace).map((p) => p.work)).toEqual([10, 40, 90]);
  });

  it("sorts by the clock before deciding a count went backwards", () => {
    const trace = [point(0.3, 90), point(0.1, 10), point(0.2, 40)];
    expect(cumulativeWork(trace)).toEqual([
      { seconds: 0.1, work: 10 },
      { seconds: 0.2, work: 40 },
      { seconds: 0.3, work: 90 },
    ]);
  });

  it("drops snapshots with no node number and no usable clock", () => {
    const trace = [point(0.1, null), point(-1, 5), point(0.2, 40)];
    expect(cumulativeWork(trace)).toEqual([{ seconds: 0.2, work: 40 }]);
  });
});

describe("withFinalCount", () => {
  // Measured driving a four-solver knapsack: CBC's trace topped out at 4,000
  // nodes under a caption reading 4,727, so the curve contradicted its own
  // number. The closing point is the end of the search, which the trace never
  // reaches.
  it("closes the curve on the number the caption shows", () => {
    const traced = [
      { seconds: 0.2, work: 2000 },
      { seconds: 0.6, work: 4000 },
    ];
    expect(withFinalCount(traced, 0.81, 4727)).toEqual([
      { seconds: 0.2, work: 2000 },
      { seconds: 0.6, work: 4000 },
      { seconds: 0.81, work: 4727 },
    ]);
  });

  it("adds a flat tail when the search found nothing more", () => {
    const traced = [
      { seconds: 0.2, work: 2000 },
      { seconds: 0.6, work: 4000 },
    ];
    expect(withFinalCount(traced, 0.9, 4000)).toHaveLength(3);
  });

  // Never invent a rise the solver did not report: a counter smaller than the
  // last snapshot, or a clock that has already passed, is left alone.
  it("refuses a closing point that goes backwards", () => {
    const traced = [
      { seconds: 0.2, work: 2000 },
      { seconds: 0.6, work: 4000 },
    ];
    expect(withFinalCount(traced, 0.5, 5000)).toEqual(traced);
    expect(withFinalCount(traced, 0.9, 3000)).toEqual(traced);
  });
});

describe("workData", () => {
  it("gives every solver its own panel with its own unit", () => {
    const data = workData({
      results: [solver("scip"), solver("highs", { nodes: 0, iterations: 5000 })],
    });
    expect(data?.panels.map((p) => [p.solver, p.unit, p.total])).toEqual([
      ["scip", "nodes", 200],
      ["highs", "iterations", 5000],
    ]);
  });

  it("divides the work by the solver's own search clock", () => {
    const data = workData({
      results: [solver("scip", { solver_time_seconds: 4, wall_time_ms: 5000 }), solver("cbc")],
    });
    expect(data?.panels[0].seconds).toBe(4);
    expect(data?.panels[0].perSecond).toBe(50);
  });

  // A search too fast to measure rounds to zero seconds, and dividing by it
  // reports an infinite rate. One millisecond is the floor the time chart uses.
  it("floors the clock so an instant search does not report an infinite rate", () => {
    const data = workData({
      results: [solver("scip", { solver_time_seconds: 0, wall_time_ms: 0 }), solver("cbc")],
    });
    expect(Number.isFinite(data?.panels[0].perSecond)).toBe(true);
    expect(data?.panels[0].perSecond).toBe(200_000);
  });

  it("draws a line from the trace and marks the others as end-only", () => {
    const data = workData({
      results: [
        solver("scip", { progress_history: [point(0.5, 30), point(1.5, 120)] }),
        solver("cbc"),
      ],
    });
    expect(data?.panels[0].points).toEqual([
      { seconds: 0.5, work: 30 },
      { seconds: 1.5, work: 120 },
      // The closing point: the search ran to 2 s and ended on 200 nodes.
      { seconds: 2, work: 200 },
    ]);
    expect(data?.panels[1].points).toEqual([]);
    expect(data?.anyEndOnly).toBe(true);
  });

  // One snapshot is the end point again, which the panel draws anyway.
  it("ignores a trace of a single point", () => {
    const data = workData({
      results: [solver("scip", { progress_history: [point(0.5, 30)] }), solver("cbc")],
    });
    expect(data?.panels[0].points).toEqual([]);
  });

  // The panel's unit is iterations, and the trace counts nodes. Putting one on
  // an axis labelled with the other would be a straight lie about the numbers.
  it("never draws a node trace on a panel measured in iterations", () => {
    const data = workData({
      results: [
        solver("glpk", { nodes: 0, progress_history: [point(0.5, 30), point(1.5, 120)] }),
        solver("cbc"),
      ],
    });
    expect(data?.panels[0].unit).toBe("iterations");
    expect(data?.panels[0].points).toEqual([]);
  });

  // CONTRACT-TEST: a solver that ran and vanished from a chart reads as one
  // nobody asked for. The two reasons stay apart because "reported no count"
  // under a row that shows a node count is simply wrong.
  it("names the solvers it left out, and why", () => {
    const data = workData({
      results: [
        solver("scip"),
        solver("cbc"),
        solver("glpk", { nodes: null, iterations: null }),
        solver("highs", { wall_time_ms: null, solver_time_seconds: null }),
      ],
    });
    expect(data?.omitted).toEqual([
      { solver: "glpk", reason: "noCount" },
      { solver: "highs", reason: "noClock" },
    ]);
  });

  it("leaves out a solver that never ran", () => {
    const data = workData({
      results: [
        solver("scip"),
        solver("cbc"),
        solver("hexaly", { status: "failed", solver_status: "unsupported" }),
      ],
    });
    expect(data?.panels.map((p) => p.solver)).toEqual(["scip", "cbc"]);
    expect(data?.omitted).toEqual([]);
  });

  it("draws nothing below two panels, because one panel compares nothing", () => {
    expect(workData({ results: [solver("scip")] })).toBeNull();
    expect(workData({ results: [] })).toBeNull();
  });

  it("shares one right edge, far enough out for the longest search", () => {
    const data = workData({
      results: [
        solver("scip", { solver_time_seconds: 0.5, wall_time_ms: 600 }),
        solver("cbc", { solver_time_seconds: 12, wall_time_ms: 12500 }),
      ],
    });
    expect(data?.maxSeconds).toBe(12);
  });

  // The trace can run past the counter's own second by a rounding's worth, and a
  // point outside the domain is a point recharts does not draw.
  it("stretches the edge to the last point of a trace", () => {
    const data = workData({
      results: [
        solver("scip", {
          solver_time_seconds: 1,
          wall_time_ms: 1000,
          progress_history: [point(0.5, 30), point(1.4, 120)],
        }),
        solver("cbc", { solver_time_seconds: 1, wall_time_ms: 1000 }),
      ],
    });
    expect(data?.maxSeconds).toBe(1.4);
  });
});
