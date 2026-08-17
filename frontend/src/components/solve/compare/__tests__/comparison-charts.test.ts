import { describe, expect, it } from "vitest";

import type { ComparisonDetail, ComparisonSolverResult } from "@/lib/types";
import {
  boundBars,
  boundDomain,
  boundOmissions,
  logDomain,
  splitBars,
  timeBars,
} from "../comparison-charts";

function result(overrides: Partial<ComparisonSolverResult> = {}): ComparisonSolverResult {
  return {
    solver_name: "scip",
    execution_id: "exe_1",
    status: "completed",
    solver_status: "optimal",
    unsupported_reason: null,
    objective_value: 100,
    dual_bound: 100,
    gap: 0,
    iterations: 10,
    nodes: 1,
    wall_time_ms: 1000,
    solver_time_seconds: 0.8,
    error_message: null,
    ...overrides,
  };
}

function comparison(results: ComparisonSolverResult[]): ComparisonDetail {
  return {
    id: "cmp_1",
    status: "completed",
    problem_name: "p",
    batch_id: null,
    source_kind: null,
    source_id: null,
    uploaded_filename: null,
    model_project_id: null,
    model_project_version_id: null,
    dataset_id: null,
    dataset_name: null,
    settings: { time_limit_seconds: 60, gap_tolerance: 0.0001, threads: 1 },
    problem_class: "MILP",
    variable_count: 10,
    constraint_count: 5,
    machine_note: null,
    results,
    agreement: null,
    error_message: null,
    created_at: "2026-08-17T00:00:00Z",
    started_at: null,
    completed_at: null,
  };
}

describe("timeBars", () => {
  it("puts the fastest first and says how many times slower the rest were", () => {
    const bars = timeBars(
      comparison([
        result({ solver_name: "scip", wall_time_ms: 4000 }),
        result({ solver_name: "highs", wall_time_ms: 1000 }),
      ]),
    );

    expect(bars.map((bar) => bar.solver)).toEqual(["highs", "scip"]);
    expect(bars[1].ratio).toBe(4);
  });

  // Zero on a logarithmic axis is not a short bar, it is no bar at all — and the
  // solver it belongs to is the one that won.
  it("floors a solve too fast to measure instead of plotting zero", () => {
    const bars = timeBars(
      comparison([
        result({ solver_name: "scip", wall_time_ms: 0 }),
        result({ solver_name: "highs", wall_time_ms: 2000 }),
      ]),
    );

    expect(bars[0].seconds).toBeGreaterThan(0);
    expect(Number.isFinite(Math.log10(bars[0].seconds))).toBe(true);
  });

  // A solver that never ran has no bar, and a chart of one bar compares nothing.
  it("draws nothing when only one solver produced a time", () => {
    expect(
      timeBars(
        comparison([
          result({ solver_name: "scip", wall_time_ms: 1000 }),
          result({ solver_name: "highs", solver_status: "unsupported", wall_time_ms: null }),
        ]),
      ),
    ).toEqual([]);
  });
});

describe("logDomain", () => {
  it("rounds out to whole powers of ten", () => {
    expect(logDomain([0.4, 37])).toEqual([0.1, 100]);
  });

  // Zero has no place on a log axis, and dropping the fastest solve would drop
  // the one that won.
  it("floors a solve too fast to measure instead of dropping it", () => {
    const [low, high] = logDomain([0, 2]);
    expect(low).toBeGreaterThan(0);
    expect(high).toBeGreaterThanOrEqual(10);
  });

  it("never collapses to a single tick", () => {
    const [low, high] = logDomain([1, 1]);
    expect(high).toBeGreaterThan(low);
  });
});

describe("boundBars", () => {
  it("spans from the bound to the answer", () => {
    const bars = boundBars(
      comparison([
        result({ solver_name: "scip", objective_value: 120, dual_bound: 100 }),
        result({ solver_name: "highs", objective_value: 110, dual_bound: 110 }),
      ]),
    );

    expect(bars[0]).toMatchObject({ solver: "scip", low: 100, span: 20, proven: false });
    expect(bars[1]).toMatchObject({ solver: "highs", span: 0, proven: true });
  });

  it("works when the bound sits above the answer, as it does when minimizing", () => {
    const bars = boundBars(
      comparison([
        result({ solver_name: "scip", objective_value: 100, dual_bound: 130 }),
        result({ solver_name: "highs", objective_value: 100, dual_bound: 100 }),
      ]),
    );
    expect(bars[0]).toMatchObject({ low: 100, span: 30 });
  });

  // An infeasible or errored run has no answer to place on the axis.
  it("leaves out a solver with no answer", () => {
    expect(
      boundBars(
        comparison([
          result({ solver_name: "scip" }),
          result({ solver_name: "highs", solver_status: "infeasible", objective_value: null }),
        ]),
      ),
    ).toEqual([]);
  });
});

describe("boundOmissions", () => {
  // A solver that ran and then vanished from the chart reads as a solver nobody
  // asked, which is the one thing a comparison must never suggest.
  it("names the solvers that ran but reported no answer", () => {
    const detail = comparison([
      result({ solver_name: "scip" }),
      result({ solver_name: "highs", solver_status: "time_limit", objective_value: null }),
      result({ solver_name: "cbc" }),
    ]);

    expect(boundBars(detail).map((bar) => bar.solver)).toEqual(["scip", "cbc"]);
    expect(boundOmissions(detail)).toEqual(["highs"]);
  });

  it("names nobody when every solver that ran is in the chart", () => {
    const detail = comparison([result({ solver_name: "scip" }), result({ solver_name: "cbc" })]);
    expect(boundOmissions(detail)).toEqual([]);
  });

  // A solver that never ran is already accounted for by its "not supported" row.
  it("does not name a solver that could not run at all", () => {
    const detail = comparison([
      result({ solver_name: "scip" }),
      result({ solver_name: "cbc" }),
      result({
        solver_name: "highs",
        status: "failed",
        solver_status: "unsupported",
        objective_value: null,
        dual_bound: null,
      }),
    ]);
    expect(boundOmissions(detail)).toEqual([]);
  });
});

describe("boundDomain", () => {
  it("covers every bar with room around it", () => {
    const [low, high] = boundDomain([
      { solver: "a", low: 100, span: 20, objective: 120, bound: 100, proven: false },
      { solver: "b", low: 90, span: 0, objective: 90, bound: 90, proven: true },
    ]);
    expect(low).toBeLessThan(90);
    expect(high).toBeGreaterThan(120);
  });

  it("still has width when every solver agrees exactly", () => {
    const [low, high] = boundDomain([
      { solver: "a", low: 5, span: 0, objective: 5, bound: 5, proven: true },
      { solver: "b", low: 5, span: 0, objective: 5, bound: 5, proven: true },
    ]);
    expect(high).toBeGreaterThan(low);
  });
});

describe("splitBars", () => {
  it("splits the wait into the search and the model building", () => {
    const bars = splitBars(
      comparison([
        result({ solver_name: "scip", wall_time_ms: 5000, solver_time_seconds: 2 }),
        result({ solver_name: "highs", wall_time_ms: 1000, solver_time_seconds: 0.4 }),
      ]),
    );

    expect(bars[0]).toMatchObject({ solver: "highs", search: 0.4 });
    expect(bars[0].build).toBeCloseTo(0.6);
    expect(bars[1]).toMatchObject({ solver: "scip", search: 2, build: 3 });
  });

  // Two clocks measure the two numbers, so rounding can put the search a
  // millisecond past the wall time. A negative segment would draw backwards.
  it("never produces a negative segment", () => {
    const bars = splitBars(
      comparison([
        result({ solver_name: "scip", wall_time_ms: 1000, solver_time_seconds: 1.002 }),
        result({ solver_name: "highs", wall_time_ms: 2000, solver_time_seconds: 1 }),
      ]),
    );
    expect(bars.every((bar) => bar.build >= 0)).toBe(true);
    expect(bars.find((bar) => bar.solver === "scip")?.search).toBeLessThanOrEqual(1);
  });

  // With no building to show, this is the time chart again on a linear axis.
  it("draws nothing when every solver went straight into the search", () => {
    expect(
      splitBars(
        comparison([
          result({ solver_name: "scip", wall_time_ms: 5000, solver_time_seconds: 4.99 }),
          result({ solver_name: "highs", wall_time_ms: 1000, solver_time_seconds: 0.999 }),
        ]),
      ),
    ).toEqual([]);
  });

  it("draws nothing when no solver reports its own search time", () => {
    expect(
      splitBars(
        comparison([
          result({ solver_name: "scip", solver_time_seconds: null }),
          result({ solver_name: "highs", solver_time_seconds: null }),
        ]),
      ),
    ).toEqual([]);
  });
});
