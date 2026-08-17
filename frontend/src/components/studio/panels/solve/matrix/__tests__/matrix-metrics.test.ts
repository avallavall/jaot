import { describe, expect, it } from "vitest";

import type { ComparisonMatrixRow, ComparisonSolverResult } from "@/lib/types";
import {
  bestInRow,
  canStopMatrix,
  cellOf,
  hardestRow,
  hasDirection,
  heatOf,
  shouldKeepPollingMatrix,
  winnerCount,
} from "../matrix-metrics";

function result(overrides: Partial<ComparisonSolverResult> = {}): ComparisonSolverResult {
  return {
    solver_name: "scip",
    execution_id: "exe_1",
    status: "completed",
    solver_status: "optimal",
    unsupported_reason: null,
    objective_value: 10,
    dual_bound: 10,
    gap: 0,
    iterations: 100,
    nodes: 5,
    wall_time_ms: 1000,
    solver_time_seconds: 0.9,
    error_message: null,
    ...overrides,
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

describe("cellOf", () => {
  it("reads the metric off the result", () => {
    const cell = cellOf(result({ wall_time_ms: 2500 }), "time");
    expect(cell).toEqual({ kind: "value", value: 2.5, reason: null, error: null });
  });

  // A cell that could not run must SAY it could not run. Falling through to an
  // empty cell reads as zero, and zero seconds is the best score on the grid.
  it("keeps a solver that cannot run out of the numbers, with its reason", () => {
    const cell = cellOf(
      result({ solver_status: "unsupported", unsupported_reason: "integer_variables" }),
      "time",
    );
    expect(cell.kind).toBe("unsupported");
    expect(cell.reason).toBe("integer_variables");
    expect(cell.value).toBeNull();
  });

  it("distinguishes waiting, failed and stopped from having no number", () => {
    expect(cellOf(result({ status: "running" }), "time").kind).toBe("waiting");
    expect(cellOf(result({ status: "cancelled" }), "time").kind).toBe("cancelled");
    expect(cellOf(result({ status: "failed", error_message: "boom" }), "time").error).toBe("boom");
    expect(cellOf(result({ nodes: null }), "nodes").kind).toBe("none");
  });
});

describe("direction", () => {
  // Lower is better for time and gap and for nothing else: a lower objective is
  // better when minimizing and worse when maximizing, and fewer nodes is not
  // better, only different.
  it("only claims a direction where one exists", () => {
    expect(hasDirection("time")).toBe(true);
    expect(hasDirection("gap")).toBe(true);
    expect(hasDirection("objective")).toBe(false);
    expect(hasDirection("nodes")).toBe(false);
    expect(hasDirection("iterations")).toBe(false);
  });

  it("has no best and no colour without a direction", () => {
    const cells = [cellOf(result(), "objective"), cellOf(result({ objective_value: 3 }), "objective")];
    expect(bestInRow(cells, "objective")).toBeNull();
    expect(heatOf(cells[0], 3, "objective")).toBeNull();
  });
});

describe("heatOf", () => {
  it("grades each cell against the best of its own row", () => {
    const best = cellOf(result({ wall_time_ms: 1000 }), "time");
    const close = cellOf(result({ wall_time_ms: 1800 }), "time");
    const behind = cellOf(result({ wall_time_ms: 5000 }), "time");
    const far = cellOf(result({ wall_time_ms: 60000 }), "time");

    expect(heatOf(best, 1, "time")).toBe("best");
    expect(heatOf(close, 1, "time")).toBe("close");
    expect(heatOf(behind, 1, "time")).toBe("behind");
    expect(heatOf(far, 1, "time")).toBe("far");
  });

  it("survives a best of zero", () => {
    const zero = cellOf(result({ gap: 0 }), "gap");
    const some = cellOf(result({ gap: 0.02 }), "gap");
    expect(heatOf(zero, 0, "gap")).toBe("best");
    expect(heatOf(some, 0, "gap")).toBe("behind");
  });
});

describe("winnerCount", () => {
  it("names the solver that came first most often", () => {
    const rows = [
      row("January", [
        result({ solver_name: "scip", wall_time_ms: 3000 }),
        result({ solver_name: "highs", wall_time_ms: 1000 }),
      ]),
      row("February", [
        result({ solver_name: "scip", wall_time_ms: 4000 }),
        result({ solver_name: "highs", wall_time_ms: 900 }),
      ]),
      row("March", [
        result({ solver_name: "scip", wall_time_ms: 1000 }),
        result({ solver_name: "highs", wall_time_ms: 8000 }),
      ]),
    ];

    expect(winnerCount(rows, "time")).toEqual({ solver: "highs", wins: 2, rowsCompared: 3 });
  });

  // A tie is not a win. With a gap tolerance most rows tie at zero, and counting
  // a tie for both solvers would manufacture a leader out of nothing.
  it("skips a row where two solvers tie", () => {
    const rows = [
      row("January", [
        result({ solver_name: "scip", gap: 0 }),
        result({ solver_name: "highs", gap: 0 }),
      ]),
    ];
    expect(winnerCount(rows, "gap")).toBeNull();
  });

  it("names nobody when the leaders are level", () => {
    const rows = [
      row("January", [
        result({ solver_name: "scip", wall_time_ms: 1000 }),
        result({ solver_name: "highs", wall_time_ms: 2000 }),
      ]),
      row("February", [
        result({ solver_name: "scip", wall_time_ms: 2000 }),
        result({ solver_name: "highs", wall_time_ms: 1000 }),
      ]),
    ];
    expect(winnerCount(rows, "time")).toBeNull();
  });

  it("claims nothing about a metric with no direction", () => {
    const rows = [
      row("January", [
        result({ solver_name: "scip", objective_value: 5 }),
        result({ solver_name: "highs", objective_value: 9 }),
      ]),
    ];
    expect(winnerCount(rows, "objective")).toBeNull();
  });

  it("ignores a row where only one solver produced a number", () => {
    const rows = [
      row("January", [
        result({ solver_name: "scip", wall_time_ms: 1000 }),
        result({ solver_name: "highs", solver_status: "unsupported" }),
      ]),
    ];
    expect(winnerCount(rows, "time")).toBeNull();
  });
});

describe("hardestRow", () => {
  // The slowest column, not the sum: one solver giving up at the time limit does
  // not make a row harder than one where every solver took that long.
  it("is the dataset whose slowest solver took longest", () => {
    const rows = [
      row("January", [
        result({ solver_name: "scip", wall_time_ms: 1000 }),
        result({ solver_name: "highs", wall_time_ms: 1000 }),
      ]),
      row("March", [
        result({ solver_name: "scip", wall_time_ms: 9000 }),
        result({ solver_name: "highs", wall_time_ms: 500 }),
      ]),
    ];
    expect(hardestRow(rows)?.dataset_name).toBe("March");
  });

  it("is nothing when no row has finished", () => {
    const rows = [row("January", [result({ status: "pending", wall_time_ms: null })])];
    expect(hardestRow(rows)).toBeNull();
  });
});

describe("polling", () => {
  // Stopping a matrix marks every unstarted row cancelled at once, but the solve
  // already inside a solver finishes and writes its verdict seconds later. A cell
  // without a verdict has to keep the polling alive on its own.
  it("keeps polling a stopped matrix whose last cell is still solving", () => {
    const batch = {
      status: "cancelled",
      rows: [row("January", [result({ status: "running" })])],
    };
    expect(shouldKeepPollingMatrix(batch)).toBe(true);
    // ...but there is nothing left to stop.
    expect(canStopMatrix(batch)).toBe(false);
  });

  // A row whose dataset never compiled has no cells of its own, so every column
  // of it reads as pending for ever. Polling on that never stops.
  it("stops polling for the cells of a row that already ended", () => {
    const failed = {
      ...row("January", [result({ status: "pending", wall_time_ms: null })]),
      status: "failed",
    };
    const batch = { status: "completed", rows: [failed] };
    expect(shouldKeepPollingMatrix(batch)).toBe(false);
    expect(cellOf(failed.results[0], "time", failed.status).kind).toBe("skipped");
  });

  it("keeps polling a pending cell while its row is still going", () => {
    const live = {
      ...row("January", [result({ status: "pending", wall_time_ms: null })]),
      status: "running",
    };
    expect(shouldKeepPollingMatrix({ status: "running", rows: [live] })).toBe(true);
    expect(cellOf(live.results[0], "time", live.status).kind).toBe("waiting");
  });

  it("stops polling once every cell has a verdict", () => {
    const batch = { status: "completed", rows: [row("January", [result()])] };
    expect(shouldKeepPollingMatrix(batch)).toBe(false);
  });

  it("polls nothing when there is no matrix", () => {
    expect(shouldKeepPollingMatrix(null)).toBe(false);
    expect(canStopMatrix(null)).toBe(false);
  });
});
