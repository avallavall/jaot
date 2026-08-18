/**
 * Taking a comparison out of the page, as rows.
 *
 * With five solvers and a dozen datasets a grid is sixty cells, and somebody is
 * going to want them in a report. The rows are built here, in the browser, off
 * the response the page already holds — the numbers are all in it, so a round
 * trip would only add a way to fail.
 *
 * Rows, not a CSV string: quoting, line endings and the UTF-8 BOM that makes
 * Excel read accents correctly are `lib/csv-utils`' business, and it already
 * gets them right for every other export in the app.
 *
 * **Numbers go in raw, never formatted.** Everything on screen goes through
 * `toLocaleString(undefined, …)`, so a browser set to Spanish renders `0,06`.
 * Writing that into a comma-separated file puts a column break in the middle of
 * a number, and a reader in another locale gets a different file from the same
 * table. A CSV is for a machine to read back.
 */
import type { ComparisonBatchDetail, ComparisonDetail, ComparisonSolverResult } from "@/lib/types";

/** What a CSV cell may hold before `quoteCell` renders it. */
type Cell = string | number | null | undefined;

/** The columns of an exported comparison, in the order the table shows them. */
const COMPARISON_COLUMNS = [
  "solver",
  "solver_version",
  "status",
  "solver_status",
  "unsupported_reason",
  "objective_value",
  "dual_bound",
  "gap",
  "wall_time_ms",
  "solver_time_seconds",
  "nodes",
  "iterations",
  "error_message",
] as const;

/** The same, prefixed with the dataset each row belongs to. */
const MATRIX_COLUMNS = [
  "dataset",
  "problem_class",
  "variables",
  "constraints",
  ...COMPARISON_COLUMNS,
] as const;

function resultCells(row: ComparisonSolverResult): Cell[] {
  return [
    row.solver_name,
    row.solver_version,
    row.status,
    row.solver_status,
    row.unsupported_reason,
    row.objective_value,
    row.dual_bound,
    row.gap,
    row.wall_time_ms,
    row.solver_time_seconds,
    row.nodes,
    row.iterations,
    row.error_message,
  ];
}

/** A single comparison as rows: a header, then one line per solver. */
export function comparisonRows(comparison: ComparisonDetail): Cell[][] {
  return [[...COMPARISON_COLUMNS], ...comparison.results.map(resultCells)];
}

/** A matrix as rows: one line per dataset AND solver, so it pivots anywhere.
 *
 * Long rather than wide. The grid on screen shows one metric at a time, and a
 * file shaped like the grid would carry the metric being looked at and drop the
 * other four. */
export function matrixRows(batch: ComparisonBatchDetail): Cell[][] {
  const rows: Cell[][] = [[...MATRIX_COLUMNS]];
  for (const matrixRow of batch.rows) {
    for (const result of matrixRow.results) {
      rows.push([
        matrixRow.dataset_name,
        matrixRow.problem_class,
        matrixRow.variable_count,
        matrixRow.constraint_count,
        ...resultCells(result),
      ]);
    }
  }
  return rows;
}

/**
 * The JSON export is the response itself, pretty-printed.
 *
 * Deliberately not a reshaped "export format": the API already documents this
 * shape, an MCP client already reads it, and a second shape would be a second
 * thing to keep true.
 */
export function toJson(payload: ComparisonDetail | ComparisonBatchDetail): string {
  return `${JSON.stringify(payload, null, 2)}\n`;
}

/** A file name that says what the file is and when it was taken. */
export function exportFilename(base: string, extension: "csv" | "json"): string {
  // Colons are not allowed in a Windows file name, and the seconds do not help
  // anyone: minute precision is enough to tell two exports apart.
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  const safe = base.replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "") || "comparison";
  return `${safe}-${stamp}.${extension}`;
}
