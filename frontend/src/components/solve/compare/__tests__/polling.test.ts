/**
 * Stopping a comparison used to freeze the column that was still solving.
 *
 * Found by driving the real page: the parent goes cancelled the moment Stop is
 * clicked, the page stopped polling on that, and the solve already inside the
 * solver kept going and wrote its verdict to a table nobody was reading any
 * more. The row said "Running" until a reload.
 */
import { describe, expect, it } from "vitest";

import type { ComparisonDetail, ComparisonSolverResult } from "@/lib/types";

import { canStop, shouldKeepPolling } from "../polling";

function row(status: string, solverName = "scip"): ComparisonSolverResult {
  return {
    solver_name: solverName,
    execution_id: "exe_1",
    status,
    solver_status: status === "completed" ? "optimal" : null,
    unsupported_reason: null,
    objective_value: null,
    dual_bound: null,
    gap: null,
    iterations: null,
    nodes: null,
    wall_time_ms: null,
    solver_time_seconds: null,
    error_message: null,
  };
}

function comparison(status: string, results: ComparisonSolverResult[]): ComparisonDetail {
  return {
    id: "cmp_1",
    status,
    problem_name: "p",
    source_kind: null,
    source_id: null,
    uploaded_filename: null,
    model_project_id: null,
    model_project_version_id: null,
    dataset_id: null,
    dataset_name: null,
    settings: { time_limit_seconds: 60, gap_tolerance: 0.0001, threads: 1 },
    problem_class: "LP",
    variable_count: 2,
    constraint_count: 2,
    machine_note: null,
    results,
    agreement: null,
    error_message: null,
    created_at: "2026-08-14T10:00:00Z",
    started_at: null,
    completed_at: null,
  };
}

describe("shouldKeepPolling", () => {
  it("polls nothing before a comparison exists", () => {
    expect(shouldKeepPolling(null)).toBe(false);
  });

  it("polls while the comparison is queued or running", () => {
    expect(shouldKeepPolling(comparison("pending", [row("pending")]))).toBe(true);
    expect(shouldKeepPolling(comparison("running", [row("running")]))).toBe(true);
  });

  it("stops once every row has a verdict", () => {
    expect(
      shouldKeepPolling(comparison("completed", [row("completed"), row("failed", "highs")])),
    ).toBe(false);
  });

  // The regression this file exists for.
  it("keeps polling after a stop while a solver is still finishing", () => {
    const stopped = comparison("cancelled", [row("completed"), row("running", "highs")]);
    expect(shouldKeepPolling(stopped)).toBe(true);
  });

  it("stops once the interrupted comparison's last solver has written its verdict", () => {
    const settled = comparison("cancelled", [row("completed"), row("cancelled", "highs")]);
    expect(shouldKeepPolling(settled)).toBe(false);
  });
});

describe("canStop", () => {
  it("offers Stop while the comparison is live", () => {
    expect(canStop(comparison("running", [row("running")]))).toBe(true);
  });

  // Nothing left to stop, even though a column is still finishing — offering
  // the button again would promise something it cannot do.
  it("does not offer Stop on a comparison that is already cancelled", () => {
    expect(canStop(comparison("cancelled", [row("running", "highs")]))).toBe(false);
  });

  it("does not offer Stop on a finished comparison", () => {
    expect(canStop(comparison("completed", [row("completed")]))).toBe(false);
  });
});
