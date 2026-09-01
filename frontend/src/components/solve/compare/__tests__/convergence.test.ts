import { describe, expect, it } from "vitest";

import type { ComparisonSolverResult, ProgressTracePoint } from "@/lib/types";

import { convergenceData, convergenceSeries, gapOf } from "../convergence";

function point(
  seconds: number,
  objective: number,
  bound: number | null = null,
  gap: number | null = null,
): ProgressTracePoint {
  return {
    iteration: 1,
    node: 0,
    objective,
    primal_bound: objective,
    dual_bound: bound,
    gap,
    elapsed_seconds: seconds,
  };
}

function solver(
  name: string,
  trace: ProgressTracePoint[] | null,
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
    iterations: 1,
    nodes: 1,
    wall_time_ms: 1000,
    solver_time_seconds: 1,
    error_message: null,
    progress_history: trace,
    ...overrides,
  };
}

describe("gapOf", () => {
  it("prefers the number the solver reported", () => {
    expect(gapOf(point(1, 100, 110, 0.05))).toBe(0.05);
  });

  it("computes it from the two bounds when the solver did not", () => {
    expect(gapOf(point(1, 100, 110))).toBeCloseTo(0.1, 10);
  });

  // CONTRACT-TEST: on a maximization, "take nothing" is a real feasible first
  // answer of exactly zero, and SCIP reports it. There is no relative gap
  // against zero. Dividing gives infinity, which a log axis cannot draw, and
  // calling it 100% would claim the solver knew something it did not.
  it("has no answer for an objective of exactly zero", () => {
    expect(gapOf(point(0.003, 0, 11328358))).toBeNull();
  });

  it("has no answer without a bound", () => {
    expect(gapOf(point(1, 100))).toBeNull();
    expect(gapOf(point(1, 100, Number.POSITIVE_INFINITY))).toBeNull();
  });

  it("reads a reported gap of zero as zero, not as missing", () => {
    expect(gapOf(point(1, 100, 100, 0))).toBe(0);
  });
});

describe("convergenceData", () => {
  it("needs two traces, because one line compares nothing", () => {
    expect(
      convergenceData([
        solver("scip", [point(0.1, 5, 6), point(0.5, 8, 9)]),
        solver("highs", null),
      ]),
    ).toBeNull();
  });

  it("builds a line per solver that reported a gap more than once", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 12), point(0.5, 8, 10)]),
      solver("cbc", [point(0.2, 4, 13), point(0.9, 8, 8)]),
    ])!;

    expect(data.lines.map((l) => l.solver)).toEqual(["scip", "cbc"]);
    expect(data.maxSeconds).toBe(0.9);
    expect(data.silent).toEqual([]);
  });

  // CONTRACT-TEST: HiGHS reports nothing while it searches and GLPK reports
  // without a clock. Dropping them silently reads as "not asked for", which is
  // the one thing they are not: they ran, and the table above shows their row.
  it("names a solver that ran and reported nothing usable", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 6), point(0.5, 8, 9)]),
      solver("cbc", [point(0.2, 4, 5), point(0.9, 8, 9)]),
      solver("highs", null),
      solver("glpk", []),
    ])!;

    expect(data.silent).toEqual(["highs", "glpk"]);
  });

  it("leaves out a solver that never ran, rather than calling it silent", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 6), point(0.5, 8, 9)]),
      solver("cbc", [point(0.2, 4, 5), point(0.9, 8, 9)]),
      solver("hexaly", null, { status: "failed", solver_status: "unsupported" }),
      solver("glpk", null, { status: "pending", solver_status: null }),
    ])!;

    expect(data.silent).toEqual([]);
    expect(data.lines).toHaveLength(2);
  });

  it("records the second each solver closed its gap", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 6), point(0.5, 8, 8, 0)]),
      solver("cbc", [point(0.2, 4, 5), point(0.9, 8, 9, 0.1)]),
    ])!;

    expect(data.lines.find((l) => l.solver === "scip")!.provedAt).toBe(0.5);
    expect(data.lines.find((l) => l.solver === "cbc")!.provedAt).toBeNull();
    expect(data.anyProved).toBe(true);
  });

  it("sorts a trace that arrived out of order", () => {
    const data = convergenceData([
      solver("scip", [point(0.9, 8, 9), point(0.1, 5, 6), point(0.4, 7, 8)]),
      solver("cbc", [point(0.2, 4, 5), point(0.8, 8, 9)]),
    ])!;

    expect(data.lines[0].points.map((p) => p.seconds)).toEqual([0.1, 0.4, 0.9]);
  });

  it("drops a snapshot with no clock instead of putting it at zero", () => {
    const data = convergenceData([
      solver("scip", [
        point(0.1, 5, 6),
        { ...point(0, 6, 7), elapsed_seconds: Number.NaN },
        point(0.5, 8, 9),
      ]),
      solver("cbc", [point(0.2, 4, 5), point(0.9, 8, 9)]),
    ])!;

    expect(data.lines[0].points.map((p) => p.seconds)).toEqual([0.1, 0.5]);
  });

  // CONTRACT-TEST: this measurement decided the chart. A 220-item knapsack on
  // SCIP and CBC: relaxation 11.3 million, trivial first answer 0, and the whole
  // search between 5.664 and 5.665 million. Plotted as objective values that is
  // one flat line; as a gap it spans decades.
  it("turns the instance that flattened the objective chart into decades", () => {
    const data = convergenceData([
      solver("scip", [
        point(0.003, 0, 11328358),
        point(0.02, 5664676, 5664707),
        point(1.1, 5664707, 5664707, 0),
      ]),
      solver("cbc", [
        point(0.04, 5000000, 5664707),
        point(0.4, 5664700, 5664707),
        point(0.8, 5664707, 5664707, 0),
      ]),
    ])!;

    // The objective-0 snapshot has no gap and never becomes a point.
    expect(data.lines[0].points).toHaveLength(2);
    const [floor, top] = data.domain;
    expect(floor).toBeGreaterThan(0);
    expect(top / floor).toBeGreaterThan(10);
    expect(data.anyProved).toBe(true);
  });

  // CONTRACT-TEST: a logarithmic axis has no zero. A domain containing it draws
  // nothing at all, which reads as a broken feature rather than as odd data.
  it("never puts zero on the axis, even when both solvers proved everything", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 5, 0), point(0.5, 5, 5, 0)]),
      solver("cbc", [point(0.2, 5, 5, 0), point(0.9, 5, 5, 0)]),
    ])!;

    expect(data.domain[0]).toBeGreaterThan(0);
    expect(data.domain[1]).toBeGreaterThan(data.domain[0]);
  });
});

describe("convergenceSeries", () => {
  // CONTRACT-TEST: what a solver held at time t is its last report at or before
  // t. Interpolating between reports would draw a gap it never had, on a chart
  // whose whole claim is what it had and when.
  it("holds each solver's last report until it reports again", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 10, 12), point(0.9, 10, 11)]),
      solver("cbc", [point(0.4, 10, 13), point(0.7, 10, 12)]),
    ])!;
    const series = convergenceSeries(data);

    expect(series.map((s) => s.seconds)).toEqual([0.1, 0.4, 0.7, 0.9]);
    expect(series.map((s) => s.scip)).toEqual([0.2, 0.2, 0.2, 0.1]);
  });

  // CONTRACT-TEST: before its first report a solver held nothing. A value there
  // draws a line starting from a gap it never had.
  it("leaves a solver out of the instants before it first reported", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 10, 12), point(0.9, 10, 11)]),
      solver("cbc", [point(0.4, 10, 13), point(0.7, 10, 12)]),
    ])!;

    expect("cbc" in convergenceSeries(data)[0]).toBe(false);
  });

  // CONTRACT-TEST: a gap of zero is the moment the search ended, and a log axis
  // cannot plot it. Dropped, the line stops short of its own conclusion.
  it("draws a closed gap on the floor rather than dropping it", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 10, 12), point(0.9, 10, 10, 0)]),
      solver("cbc", [point(0.4, 10, 13), point(0.7, 10, 12)]),
    ])!;
    const series = convergenceSeries(data);
    const last = series[series.length - 1];

    expect(last.scip).toBe(data.domain[0]);
    expect(last.scip).toBeGreaterThan(0);
  });
});
