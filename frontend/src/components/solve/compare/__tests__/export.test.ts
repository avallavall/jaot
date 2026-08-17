/**
 * Taking a comparison out of the page.
 *
 * The dangerous failure here is a file that looks fine and is wrong: a number
 * written in the reader's locale, a quote that ends a field early, a row that
 * silently vanished. All three produce a spreadsheet nobody questions.
 */
import { describe, it, expect } from "vitest";

import type { ComparisonBatchDetail, ComparisonDetail, ComparisonSolverResult } from "@/lib/types";
import { comparisonToCsv, exportFilename, matrixToCsv, toJson } from "../export";

function result(overrides: Partial<ComparisonSolverResult> = {}): ComparisonSolverResult {
  return {
    solver_name: "scip",
    solver_version: "10.0",
    execution_id: "exe_1",
    status: "completed",
    solver_status: "optimal",
    unsupported_reason: null,
    objective_value: 5400.5,
    dual_bound: 5400.5,
    gap: 0.0625,
    iterations: 1011,
    nodes: 201,
    wall_time_ms: 12248,
    solver_time_seconds: 12.027,
    error_message: null,
    ...overrides,
  };
}

function comparison(rows: ComparisonSolverResult[]): ComparisonDetail {
  return {
    id: "cmp_1",
    status: "completed",
    problem_name: "Burn-in plan",
    batch_id: null,
    source_kind: "model_project",
    source_id: "prj_1",
    uploaded_filename: null,
    model_project_id: "prj_1",
    model_project_version_id: null,
    dataset_id: null,
    dataset_name: null,
    settings: { time_limit_seconds: 60, gap_tolerance: 0.0001, threads: 4 },
    problem_class: "MILP",
    variable_count: 1342,
    constraint_count: 3558,
    machine_note: "runner (queue solve_compare, concurrency 1)",
    results: rows,
    agreement: null,
    error_message: null,
    created_at: "2026-08-18T09:00:00Z",
    started_at: "2026-08-18T09:00:01Z",
    completed_at: "2026-08-18T09:01:00Z",
  } as ComparisonDetail;
}

describe("comparisonToCsv", () => {
  it("writes one line per solver, plus a header", () => {
    const csv = comparisonToCsv(comparison([result(), result({ solver_name: "highs" })]));
    const lines = csv.trimEnd().split("\r\n");
    expect(lines).toHaveLength(3);
    expect(lines[0].startsWith("solver,solver_version,status")).toBe(true);
    expect(lines[1].startsWith("scip,10.0,completed,optimal")).toBe(true);
    expect(lines[2].startsWith("highs,")).toBe(true);
  });

  // The whole reason this module exists rather than reusing what is on screen:
  // every number in the table goes through toLocaleString, so a browser set to
  // Spanish renders 0,0625. Writing that into a comma-separated file puts a
  // column break inside a number, and two readers get different files from one
  // table.
  it("writes raw numbers, never the reader's locale", () => {
    const csv = comparisonToCsv(comparison([result({ gap: 0.0625, objective_value: 5400.5 })]));
    expect(csv).toContain("5400.5");
    expect(csv).toContain("0.0625");
    expect(csv).not.toContain("5400,5");
    expect(csv).not.toContain("0,0625");
  });

  // An error message is free text and routinely carries all three.
  it("quotes a field with a comma, a quote or a newline", () => {
    const csv = comparisonToCsv(
      comparison([result({ error_message: 'CBC said "no", then\nstopped' })]),
    );
    expect(csv).toContain('"CBC said ""no"", then\nstopped"');
  });

  it("leaves a missing value empty rather than writing null", () => {
    const csv = comparisonToCsv(
      comparison([
        result({
          solver_status: "unsupported",
          unsupported_reason: "integer_variables",
          objective_value: null,
          dual_bound: null,
          gap: null,
          nodes: null,
          iterations: null,
          wall_time_ms: null,
          solver_time_seconds: null,
          solver_version: null,
        }),
      ]),
    );
    expect(csv).not.toContain("null");
    expect(csv).not.toContain("undefined");
    expect(csv).toContain("integer_variables");
  });

  // A solver that could not run still has a row in the table, for the same
  // reason it has one here: a missing line reads as "I did not ask for it".
  it("keeps the row of a solver that never ran", () => {
    const csv = comparisonToCsv(
      comparison([result(), result({ solver_name: "hexaly", solver_status: "unsupported" })]),
    );
    expect(csv.trimEnd().split("\r\n")).toHaveLength(3);
    expect(csv).toContain("hexaly");
  });
});

describe("matrixToCsv", () => {
  const batch = {
    batch_id: "cmb_1",
    status: "completed",
    project_id: "prj_1",
    project_name: "Line balancing",
    model_project_version_id: null,
    settings: { time_limit_seconds: 60, gap_tolerance: 0.0001, threads: 4 },
    solver_names: ["scip", "highs"],
    machine_note: "runner",
    rows: [
      {
        comparison_id: "cmp_1",
        dataset_id: "dst_jan",
        dataset_name: "January",
        status: "completed",
        problem_class: "MILP",
        variable_count: 1342,
        constraint_count: 3558,
        error_message: null,
        results: [result(), result({ solver_name: "highs" })],
      },
      {
        comparison_id: "cmp_2",
        dataset_id: "dst_feb",
        dataset_name: "February",
        status: "completed",
        problem_class: "MILP",
        variable_count: 900,
        constraint_count: 2100,
        error_message: null,
        results: [result(), result({ solver_name: "highs" })],
      },
    ],
    created_at: "2026-08-18T09:00:00Z",
    completed_at: "2026-08-18T09:10:00Z",
  } as ComparisonBatchDetail;

  // Long, not wide. The grid on screen shows one metric at a time; a file
  // shaped like the grid would carry the metric being looked at and drop the
  // other four.
  it("writes one line per dataset and solver", () => {
    const lines = matrixToCsv(batch).trimEnd().split("\r\n");
    expect(lines).toHaveLength(5); // header + 2 datasets x 2 solvers
    expect(lines[0].startsWith("dataset,problem_class,variables,constraints,solver")).toBe(true);
    expect(lines[1].startsWith("January,MILP,1342,3558,scip")).toBe(true);
    expect(lines[4].startsWith("February,MILP,900,2100,highs")).toBe(true);
  });
});

describe("toJson", () => {
  it("is the response itself, so it cannot drift from the documented shape", () => {
    const detail = comparison([result()]);
    expect(JSON.parse(toJson(detail))).toEqual(detail);
  });
});

describe("exportFilename", () => {
  it("makes a name a file system will accept", () => {
    const name = exportFilename("Burn-in plan / Q3", "csv");
    expect(name).toMatch(/^Burn-in-plan-Q3-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}\.csv$/);
    expect(name).not.toContain(":");
    expect(name).not.toContain("/");
  });

  it("falls back to a name rather than an empty one", () => {
    expect(exportFilename("///", "json")).toMatch(/^comparison-/);
  });
});
