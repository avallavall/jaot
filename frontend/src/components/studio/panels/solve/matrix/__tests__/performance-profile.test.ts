import { describe, expect, it } from "vitest";

import type { ComparisonMatrixRow, ComparisonSolverResult } from "@/lib/types";

import {
  MIN_INSTANCES_FOR_PROFILE,
  performanceProfile,
  profileSeries,
} from "../performance-profile";

function result(
  solver: string,
  ms: number | null,
  solverStatus: string | null = "optimal",
  status = "completed",
): ComparisonSolverResult {
  return {
    solver_name: solver,
    execution_id: `exe_${solver}`,
    status,
    solver_status: solverStatus,
    unsupported_reason: null,
    objective_value: 1,
    dual_bound: 1,
    gap: 0,
    iterations: 1,
    nodes: 1,
    wall_time_ms: ms,
    solver_time_seconds: ms == null ? null : ms / 1000,
    error_message: null,
  };
}

function row(name: string, results: ComparisonSolverResult[]): ComparisonMatrixRow {
  return {
    comparison_id: `cmp_${name}`,
    dataset_id: `ds_${name}`,
    dataset_name: name,
    status: "completed",
    problem_class: "MILP",
    variable_count: 10,
    constraint_count: 5,
    error_message: null,
    results,
  };
}

/** Five datasets where "fast" always beats "slow" by exactly 2x. */
function twoSolverBatch(): ComparisonMatrixRow[] {
  return [1, 2, 3, 4, 5].map((n) =>
    row(`d${n}`, [result("fast", 1000 * n), result("slow", 2000 * n)]),
  );
}

describe("performanceProfile", () => {
  it("says nothing below five datasets", () => {
    const rows = twoSolverBatch().slice(0, MIN_INSTANCES_FOR_PROFILE - 1);
    expect(performanceProfile(rows, ["fast", "slow"])).toBeNull();
  });

  it("puts the outright winner at 1 and the 2x solver at 2", () => {
    const p = performanceProfile(twoSolverBatch(), ["fast", "slow"]);
    expect(p).not.toBeNull();
    expect(p!.instances).toBe(5);

    const fast = p!.curves.find((c) => c.solver === "fast")!;
    const slow = p!.curves.find((c) => c.solver === "slow")!;
    expect(fast.wins).toBe(5);
    expect(slow.wins).toBe(0);

    const series = profileSeries(p!);
    const at1 = series.find((s) => s.tau === 1)!;
    expect(at1.fast).toBe(1); // fast solved every dataset at ratio 1
    expect(at1.slow).toBe(0); // slow never matched the best time

    const atEnd = series[series.length - 1];
    expect(atEnd.fast).toBe(1);
    expect(atEnd.slow).toBe(1); // by 2x, slow has caught up on all five
  });

  // CONTRACT-TEST: a run that hit the time limit with a solution in hand did not
  // solve the dataset. Counting it would put the solver that gives up first at
  // the top of the chart.
  it("does not count a feasible-but-unproven run as solved", () => {
    const rows = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [result("fast", 1000 * n), result("slow", 10, "feasible")]),
    );
    // "slow" answered in 10 ms every time and proved none of it, so it earns no
    // curve. That leaves one curve, and one curve compares nothing: null.
    expect(performanceProfile(rows, ["fast", "slow"])).toBeNull();

    // The same batch with slow's answers PROVEN does produce two curves, which
    // is what makes the line above about the proof and not about the times.
    const proven = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [result("fast", 1000 * n), result("slow", 10)]),
    );
    expect(performanceProfile(proven, ["fast", "slow"])!.curves).toHaveLength(2);
  });

  it("counts infeasible and unbounded as proofs", () => {
    const rows = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [
        result("a", 1000 * n, n % 2 === 0 ? "infeasible" : "unbounded"),
        result("b", 3000 * n),
      ]),
    );
    const p = performanceProfile(rows, ["a", "b"])!;
    expect(p.curves.find((c) => c.solver === "a")!.solved).toBe(5);
    expect(p.curves.find((c) => c.solver === "a")!.wins).toBe(5);
  });

  // CONTRACT-TEST: a dataset nobody proved separates no two solvers. Leaving it
  // in the denominator lowers every curve by the same amount, which changes the
  // axis and not the answer.
  it("drops a dataset nobody solved from the denominator", () => {
    const rows = [
      ...twoSolverBatch(),
      row("nobody", [result("fast", 5, "time_limit"), result("slow", 5, "time_limit")]),
    ];
    const p = performanceProfile(rows, ["fast", "slow"])!;
    expect(p.instances).toBe(5);
    const series = profileSeries(p);
    expect(series[series.length - 1].fast).toBe(1);
  });

  it("names a solver that proved nothing instead of drawing it flat at zero", () => {
    const rows = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [
        result("fast", 1000 * n),
        result("slow", 2000 * n),
        result("absent", null, "unsupported", "completed"),
      ]),
    );
    const p = performanceProfile(rows, ["fast", "slow", "absent"])!;
    expect(p.neverSolved).toEqual(["absent"]);
    expect(p.curves.map((c) => c.solver).sort()).toEqual(["fast", "slow"]);
  });

  // CONTRACT-TEST: a curve that stops at its last ratio reads as a solver that
  // got worse further right. It has to be carried flat to the end of the axis.
  it("carries every curve to the end of the axis", () => {
    const rows = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [
        result("fast", 1000),
        // slow solves only the first three
        result("slow", n <= 3 ? 4000 : 10, n <= 3 ? "optimal" : "time_limit"),
      ]),
    );
    const p = performanceProfile(rows, ["fast", "slow"])!;
    const series = profileSeries(p);
    const last = series[series.length - 1];
    expect(last.tau).toBe(p.maxRatio);
    expect(last.fast).toBe(1);
    expect(last.slow).toBeCloseTo(3 / 5, 10);
  });

  it("floors a solve too fast to measure so it cannot divide by zero", () => {
    const rows = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [result("fast", 0), result("slow", 1000 * n)]),
    );
    const p = performanceProfile(rows, ["fast", "slow"])!;
    expect(Number.isFinite(p.maxRatio)).toBe(true);
    for (const point of profileSeries(p)) {
      expect(Number.isFinite(point.tau)).toBe(true);
    }
  });

  it("never places a ratio below 1, whatever rounding does", () => {
    const rows = [1, 2, 3, 4, 5].map((n) =>
      row(`d${n}`, [result("a", 1000 + n), result("b", 1000 + n)]),
    );
    const p = performanceProfile(rows, ["a", "b"])!;
    for (const curve of p.curves) {
      for (const point of curve.points) expect(point.tau).toBeGreaterThanOrEqual(1);
    }
  });

  it("a tie on a dataset is a win for both, because both were the fastest", () => {
    const rows = [1, 2, 3, 4, 5].map((n) => row(`d${n}`, [result("a", 500), result("b", 500)]));
    const p = performanceProfile(rows, ["a", "b"])!;
    expect(p.curves.find((c) => c.solver === "a")!.wins).toBe(5);
    expect(p.curves.find((c) => c.solver === "b")!.wins).toBe(5);
  });

  it("series is sorted by tau and starts at 1", () => {
    const p = performanceProfile(twoSolverBatch(), ["fast", "slow"])!;
    const series = profileSeries(p);
    expect(series[0].tau).toBe(1);
    for (let i = 1; i < series.length; i += 1) {
      expect(series[i].tau).toBeGreaterThan(series[i - 1].tau);
    }
  });
});
