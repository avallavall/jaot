/**
 * Taking a comparison out of the page.
 *
 * With five solvers and a dozen datasets a grid is sixty cells, and somebody is
 * going to want them in a report or a notebook. Both formats are built here, in
 * the browser, off the response the page already holds — the numbers are all in
 * it, so a round trip would only add a way to fail.
 *
 * **Numbers are written raw, never formatted.** Everything on screen goes
 * through `toLocaleString(undefined, …)`, so a browser set to Spanish renders
 * `0,06`. Writing that into a comma-separated file puts a column break in the
 * middle of a number, and a reader in another locale gets a different file from
 * the same table. A CSV is for a machine to read back.
 */
import type { ComparisonBatchDetail, ComparisonDetail, ComparisonSolverResult } from "@/lib/types";

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

/** The same, plus the dataset each row belongs to. */
const MATRIX_COLUMNS = ["dataset", "problem_class", "variables", "constraints", ...COMPARISON_COLUMNS] as const;

/**
 * One CSV field, quoted only when it has to be.
 *
 * RFC 4180: a field containing a comma, a quote or a newline is wrapped in
 * quotes and its own quotes are doubled. An error message is free text and
 * routinely contains all three.
 */
function csvField(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replaceAll('"', '""')}"`;
}

function csvRow(values: readonly (string | number | null | undefined)[]): string {
  return values.map(csvField).join(",");
}

function resultFields(row: ComparisonSolverResult): (string | number | null | undefined)[] {
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

/** A single comparison as CSV: one line per solver. */
export function comparisonToCsv(comparison: ComparisonDetail): string {
  const lines = [csvRow(COMPARISON_COLUMNS)];
  for (const row of comparison.results) {
    lines.push(csvRow(resultFields(row)));
  }
  // A trailing newline: every tool that reads CSV expects one, and a file
  // without it makes some of them drop the last row.
  return `${lines.join("\r\n")}\r\n`;
}

/** A matrix as CSV: one line per dataset and solver, so it pivots anywhere. */
export function matrixToCsv(batch: ComparisonBatchDetail): string {
  const lines = [csvRow(MATRIX_COLUMNS)];
  for (const matrixRow of batch.rows) {
    for (const result of matrixRow.results) {
      lines.push(
        csvRow([
          matrixRow.dataset_name,
          matrixRow.problem_class,
          matrixRow.variable_count,
          matrixRow.constraint_count,
          ...resultFields(result),
        ]),
      );
    }
  }
  return `${lines.join("\r\n")}\r\n`;
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

/**
 * Hand the file to the browser.
 *
 * An object URL rather than a data: URI — a matrix of sixty rows is small, but
 * a data: URI has a length ceiling in some browsers and this is the path that
 * grows. Revoked on the next tick, once the click has been dispatched.
 */
export function downloadText(filename: string, mime: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
