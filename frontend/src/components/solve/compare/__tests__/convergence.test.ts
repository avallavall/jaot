import { describe, expect, it } from "vitest";

import type { ComparisonSolverResult, ProgressTracePoint } from "@/lib/types";

import { convergenceData, convergenceSeries } from "../convergence";

function point(
  seconds: number,
  objective: number,
  bound: number | null = null,
): ProgressTracePoint {
  return {
    iteration: 1,
    node: 0,
    objective,
    primal_bound: objective,
    dual_bound: bound,
    gap: null,
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

describe("convergenceData", () => {
  it("needs two traces, because one line compares nothing", () => {
    const only = [
      solver("scip", [point(0.1, 5), point(0.5, 8)]),
      solver("highs", null),
    ];
    expect(convergenceData(only)).toBeNull();
  });

  it("builds a line per solver that reported more than once", () => {
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
  // the one thing they are not — they ran, and the table above shows their row.
  it("names a solver that ran and reported nothing", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5), point(0.5, 8)]),
      solver("cbc", [point(0.2, 4), point(0.9, 8)]),
      solver("highs", null),
      solver("glpk", []),
    ])!;

    expect(data.silent).toEqual(["highs", "glpk"]);
  });

  it("leaves out a solver that never ran, rather than calling it silent", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5), point(0.5, 8)]),
      solver("cbc", [point(0.2, 4), point(0.9, 8)]),
      solver("hexaly", null, { status: "failed", solver_status: "unsupported" }),
      solver("glpk", null, { status: "pending", solver_status: null }),
    ])!;

    expect(data.silent).toEqual([]);
    expect(data.lines).toHaveLength(2);
  });

  it("a single point is not a curve, it is where the table already said", () => {
    // cbc reported once, so it earns no line. That leaves one line, and one
    // line compares nothing: null.
    expect(
      convergenceData([
        solver("scip", [point(0.1, 5), point(0.5, 8)]),
        solver("cbc", [point(0.4, 7)]),
      ]),
    ).toBeNull();

    // Give cbc a second report and both lines appear, which is what makes the
    // line above about the number of reports and not about cbc.
    const data = convergenceData([
      solver("scip", [point(0.1, 5), point(0.5, 8)]),
      solver("cbc", [point(0.4, 7), point(0.6, 8)]),
    ])!;
    expect(data.lines).toHaveLength(2);
    expect(data.silent).toEqual([]);
  });

  it("sorts a trace that arrived out of order", () => {
    const data = convergenceData([
      solver("scip", [point(0.9, 8), point(0.1, 5), point(0.4, 7)]),
      solver("cbc", [point(0.2, 4), point(0.8, 8)]),
    ])!;

    expect(data.lines[0].points.map((p) => p.seconds)).toEqual([0.1, 0.4, 0.9]);
  });

  it("drops a point with no clock instead of putting it at zero", () => {
    const data = convergenceData([
      solver("scip", [
        point(0.1, 5),
        { ...point(0, 6), elapsed_seconds: Number.NaN },
        point(0.5, 8),
      ]),
      solver("cbc", [point(0.2, 4), point(0.9, 8)]),
    ])!;

    expect(data.lines[0].points.map((p) => p.seconds)).toEqual([0.1, 0.5]);
  });

  it("keeps a bound only when it is a real number", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 12), { ...point(0.5, 8), dual_bound: Number.POSITIVE_INFINITY }]),
      solver("cbc", [point(0.2, 4), point(0.9, 8)]),
    ])!;

    expect(data.lines[0].points.map((p) => p.bound)).toEqual([12, null]);
  });
});

describe("convergenceSeries", () => {
  // CONTRACT-TEST: what a solver "held" at time t is its last report at or
  // before t. Interpolating between reports would draw an incumbent the solver
  // never had, on a chart whose whole claim is what it had and when.
  it("holds each solver's last report until it reports again", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5), point(0.9, 8)]),
      solver("cbc", [point(0.4, 6), point(0.7, 7)]),
    ])!;
    const series = convergenceSeries(data);

    expect(series.map((s) => s.seconds)).toEqual([0.1, 0.4, 0.7, 0.9]);
    expect(series.map((s) => s.scip)).toEqual([5, 5, 5, 8]);
    expect(series.map((s) => s.cbc)).toEqual([undefined, 6, 7, 7]);
  });

  // CONTRACT-TEST: before its first report a solver held nothing. A zero there
  // draws a line rising from the floor, which is a search it never made.
  it("leaves a solver out of the instants before it first reported", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5), point(0.9, 8)]),
      solver("cbc", [point(0.4, 6), point(0.7, 7)]),
    ])!;
    const series = convergenceSeries(data);

    expect("cbc" in series[0]).toBe(false);
  });

  it("carries the bound on its own key", () => {
    const data = convergenceData([
      solver("scip", [point(0.1, 5, 12), point(0.9, 8, 9)]),
      solver("cbc", [point(0.4, 6, 11), point(0.7, 7, 10)]),
    ])!;
    const series = convergenceSeries(data);

    expect(series[series.length - 1].scip__bound).toBe(9);
    expect(series[series.length - 1].cbc__bound).toBe(10);
  });
});
