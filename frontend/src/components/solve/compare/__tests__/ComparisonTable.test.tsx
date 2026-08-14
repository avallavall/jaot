/**
 * The comparison table is read as evidence, so these tests guard what a reader
 * would wrongly conclude if the rendering slipped: a missing row read as a zero,
 * two correct solvers read as one broken one, and timings read across machines.
 *
 * The suite's setup replaces next-intl with a stub that returns the key path, so
 * the assertions below name keys rather than English. Whether every key exists
 * in all five locales is `npm run check-i18n`'s job, not this file's.
 */
import { describe, expect, it } from "vitest";

import type { ComparisonDetail, ComparisonSolverResult } from "@/lib/types";

function row(overrides: Partial<ComparisonSolverResult>): ComparisonSolverResult {
  return {
    solver_name: "scip",
    execution_id: "exe_1",
    status: "completed",
    solver_status: "optimal",
    unsupported_reason: null,
    objective_value: 24,
    dual_bound: 24,
    gap: 0,
    iterations: 12,
    nodes: 1,
    wall_time_ms: 340,
    solver_time_seconds: 0.3,
    error_message: null,
    ...overrides,
  };
}

function comparison(overrides: Partial<ComparisonDetail> = {}): ComparisonDetail {
  return {
    id: "cmp_1",
    status: "completed",
    problem_name: "compare-me",
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
    machine_note: "worker-7 (queue solve_compare, concurrency 1)",
    results: [row({}), row({ solver_name: "highs", wall_time_ms: 120 })],
    agreement: {
      compared_solvers: ["scip", "highs"],
      objectives_agree: true,
      solutions_identical: true,
      max_objective_delta: 0,
      alternative_optima: false,
    },
    error_message: null,
    created_at: "2026-08-14T10:00:00Z",
    started_at: "2026-08-14T10:00:01Z",
    completed_at: "2026-08-14T10:00:03Z",
    ...overrides,
  };
}

async function renderTable(detail: ComparisonDetail) {
  const { render } = await import("@testing-library/react");
  const { ComparisonTable } = await import("../ComparisonTable");

  const { container } = render(<ComparisonTable comparison={detail} />);
  const bodyRows = Array.from(container.querySelectorAll("tbody tr"));
  return {
    container,
    text: container.textContent ?? "",
    /** Rows in the order the table renders them, which is the order asked for. */
    rows: bodyRows.map((tr) => tr.textContent ?? ""),
  };
}

describe("ComparisonTable", () => {
  it("shows one row per solver, in the order they were asked for", async () => {
    const { rows } = await renderTable(comparison());
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("scip");
    expect(rows[1]).toContain("highs");
  });

  // A solver that could not run must say so. A blank cell in a comparison is
  // read as zero, which is a wrong answer rather than a missing one.
  it("names the reason a solver could not run", async () => {
    const { rows } = await renderTable(
      comparison({
        results: [
          row({}),
          row({
            solver_name: "glpk",
            status: "failed",
            solver_status: "unsupported",
            unsupported_reason: "integer_variables",
            objective_value: null,
            gap: null,
            wall_time_ms: null,
            nodes: null,
            iterations: null,
          }),
        ],
        agreement: null,
      }),
    );

    expect(rows[1]).toContain("solverCompare.status.unsupported");
    expect(rows[1]).toContain("solverCompare.unsupportedReason.integer_variables");
    // And its empty measurements read as "no value", never as zero.
    expect(rows[1]).toContain("—");
    expect(rows[1]).not.toContain("0%");
  });

  // Same objective, different variables: both solvers are right. Without this
  // line a reader compares two solutions and concludes one is broken.
  it("explains alternative optima instead of leaving them to be guessed", async () => {
    const { text } = await renderTable(
      comparison({
        agreement: {
          compared_solvers: ["scip", "highs"],
          objectives_agree: true,
          solutions_identical: false,
          max_objective_delta: 0,
          alternative_optima: true,
        },
      }),
    );

    expect(text).toContain("solverCompare.agreement.alternativeOptima");
    expect(text).not.toContain("solverCompare.agreement.identical");
  });

  it("flags solvers that disagree about the objective", async () => {
    const { text } = await renderTable(
      comparison({
        agreement: {
          compared_solvers: ["scip", "highs"],
          objectives_agree: false,
          solutions_identical: false,
          max_objective_delta: 4.5,
          alternative_optima: false,
        },
      }),
    );

    expect(text).toContain("solverCompare.agreement.objectivesDiffer");
  });

  it("says nothing about agreement when only one solver finished", async () => {
    const { text } = await renderTable(
      comparison({
        agreement: {
          compared_solvers: ["scip"],
          objectives_agree: null,
          solutions_identical: null,
          max_objective_delta: null,
          alternative_optima: false,
        },
      }),
    );

    expect(text).not.toContain("solverCompare.agreement.");
  });

  // The seconds mean nothing without the terms and the machine that produced
  // them, so both ride above the table rather than in a tooltip.
  it("states the shared conditions, the machine and how far they carry", async () => {
    const { text } = await renderTable(comparison());
    expect(text).toContain("solverCompare.conditions.terms");
    expect(text).toContain("worker-7");
    expect(text).toContain("solverCompare.conditions.scope");
  });

  it("marks the quickest solver that actually answered", async () => {
    const { rows } = await renderTable(comparison());
    // highs at 120 ms against scip at 340 ms.
    expect(rows[1]).toContain("solverCompare.table.fastest");
    expect(rows[0]).not.toContain("solverCompare.table.fastest");
  });

  // "13 s" next to "0,1 s" is two numbers; "130×" is the answer the reader was
  // going to work out anyway.
  it("says how much slower each solver was than the quickest", async () => {
    const { rows } = await renderTable(
      comparison({
        results: [
          row({ wall_time_ms: 1000 }),
          row({ solver_name: "highs", wall_time_ms: 100 }),
        ],
      }),
    );
    expect(rows[0]).toContain("10×");
    // The quickest is not labelled "1×" — it is the baseline.
    expect(rows[1]).not.toContain("×");
  });

  it("names the problem and its size above the numbers", async () => {
    const { text } = await renderTable(comparison());
    expect(text).toContain("solverCompare.conditions.problem");
  });

  it("shows the best bound next to the objective", async () => {
    const { rows } = await renderTable(
      comparison({
        results: [
          row({ objective_value: 100, dual_bound: 120, gap: 0.2 }),
          row({ solver_name: "highs", objective_value: 100, dual_bound: null, gap: null }),
        ],
        agreement: null,
      }),
    );
    expect(rows[0]).toContain("120");
    // A solver that proved no bound shows nothing, not a zero.
    expect(rows[1]).toContain("—");
  });

  it("does not crown a fastest when only one solver answered", async () => {
    const { text } = await renderTable(
      comparison({
        results: [
          row({}),
          row({
            solver_name: "highs",
            status: "failed",
            solver_status: "unsupported",
            unsupported_reason: "not_available",
            wall_time_ms: null,
          }),
        ],
        agreement: null,
      }),
    );
    expect(text).not.toContain("solverCompare.table.fastest");
  });

  it("renders a queued row as pending rather than as a zero", async () => {
    const { rows } = await renderTable(
      comparison({
        status: "running",
        results: [
          row({}),
          row({
            solver_name: "highs",
            status: "pending",
            solver_status: null,
            objective_value: null,
            gap: null,
            wall_time_ms: null,
            nodes: null,
            iterations: null,
          }),
        ],
        agreement: null,
      }),
    );

    expect(rows[1]).toContain("solverCompare.status.pending");
    expect(rows[1]).toContain("—");
  });

  it("shows the message of a solver that broke", async () => {
    const { rows } = await renderTable(
      comparison({
        results: [
          row({}),
          row({
            solver_name: "highs",
            status: "completed",
            solver_status: "error",
            objective_value: null,
            error_message: "HiGHS ran out of memory",
          }),
        ],
        agreement: null,
      }),
    );

    expect(rows[1]).toContain("solverCompare.status.error");
    expect(rows[1]).toContain("HiGHS ran out of memory");
  });
});
