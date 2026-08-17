import type { ComparisonMatrixRow, ComparisonSolverResult } from "@/lib/types";

/** What a cell of the matrix shows. The grid never changes shape; only this. */
export type MatrixMetric = "time" | "objective" | "gap" | "nodes" | "iterations";

export const MATRIX_METRICS: readonly MatrixMetric[] = [
  "time",
  "objective",
  "gap",
  "nodes",
  "iterations",
] as const;

/**
 * Whether a smaller number is a better one for this metric.
 *
 * Only two metrics have an answer. A lower objective is better when minimizing
 * and worse when maximizing, and the matrix does not know the sense; fewer nodes
 * or iterations is not better either, it is a different way of working. Claiming
 * a winner on those would be inventing one, so the metrics without a direction
 * get no winner line and no colour.
 */
const LOWER_IS_BETTER: Record<MatrixMetric, boolean> = {
  time: true,
  gap: true,
  objective: false,
  nodes: false,
  iterations: false,
};

export function hasDirection(metric: MatrixMetric): boolean {
  return LOWER_IS_BETTER[metric];
}

/** Why a cell holds no number. Never blank: a blank cell is read as zero. */
export type CellKind = "value" | "waiting" | "unsupported" | "failed" | "cancelled" | "none";

export interface MatrixCell {
  kind: CellKind;
  /** Set only when kind is "value". */
  value: number | null;
  /** Set when kind is "unsupported": the machine-readable reason code. */
  reason: string | null;
  /** Set when kind is "failed". */
  error: string | null;
}

const WAITING_STATUSES = new Set(["pending", "running"]);

/** Turn one solver's result into the cell for the chosen metric. */
export function cellOf(result: ComparisonSolverResult, metric: MatrixMetric): MatrixCell {
  if (result.solver_status === "unsupported") {
    return { kind: "unsupported", value: null, reason: result.unsupported_reason, error: null };
  }
  if (WAITING_STATUSES.has(result.status)) {
    return { kind: "waiting", value: null, reason: null, error: null };
  }
  if (result.status === "cancelled") {
    return { kind: "cancelled", value: null, reason: null, error: null };
  }
  if (result.status === "failed") {
    return { kind: "failed", value: null, reason: null, error: result.error_message };
  }

  const value = valueOf(result, metric);
  if (value === null || !Number.isFinite(value)) {
    return { kind: "none", value: null, reason: null, error: null };
  }
  return { kind: "value", value, reason: null, error: null };
}

function valueOf(result: ComparisonSolverResult, metric: MatrixMetric): number | null {
  switch (metric) {
    case "time":
      // Wall time around the whole call, in seconds — the number the table shows
      // everywhere else, because it is the wait.
      return result.wall_time_ms === null ? null : result.wall_time_ms / 1000;
    case "objective":
      return result.objective_value;
    case "gap":
      return result.gap;
    case "nodes":
      return result.nodes;
    case "iterations":
      return result.iterations;
  }
}

/** The best number in one row, or null when the row has nothing to compare. */
export function bestInRow(cells: MatrixCell[], metric: MatrixMetric): number | null {
  if (!hasDirection(metric)) return null;
  const values = cells
    .filter((cell) => cell.kind === "value" && cell.value !== null)
    .map((cell) => cell.value as number);
  return values.length === 0 ? null : Math.min(...values);
}

/** How far off the best this cell is. Four steps, because the eye reads four. */
export type Heat = "best" | "close" | "behind" | "far";

/**
 * Colour one cell against the best of ITS OWN row.
 *
 * Normalized per row and never across rows: two datasets of the same model can
 * differ by two orders of magnitude, and a scale spanning both would paint every
 * easy row the same shade.
 */
export function heatOf(cell: MatrixCell, best: number | null, metric: MatrixMetric): Heat | null {
  if (!hasDirection(metric) || cell.kind !== "value" || cell.value === null) return null;
  if (best === null) return null;
  // A best of zero (a gap already closed, or a solve under a millisecond) makes
  // the ratio meaningless. Everything that also reached zero is best; the rest
  // is simply behind.
  if (best <= 0) return cell.value <= 0 ? "best" : "behind";

  const ratio = cell.value / best;
  if (ratio <= 1.05) return "best";
  if (ratio <= 2) return "close";
  if (ratio <= 10) return "behind";
  return "far";
}

export interface WinnerCount {
  solver: string;
  wins: number;
  /** Rows that produced a single winner. The rest had a tie or no numbers. */
  rowsCompared: number;
}

/**
 * Which solver came first most often, for a metric that has a first.
 *
 * A row where two solvers tie is not counted for either: a tie is not a win, and
 * with a gap tolerance most rows tie at zero. Returns null when no row produced a
 * single winner, which is the honest answer rather than a made-up one.
 */
export function winnerCount(rows: ComparisonMatrixRow[], metric: MatrixMetric): WinnerCount | null {
  if (!hasDirection(metric)) return null;

  const wins = new Map<string, number>();
  let rowsCompared = 0;

  for (const row of rows) {
    const scored = row.results
      .map((result) => ({ solver: result.solver_name, cell: cellOf(result, metric) }))
      .filter((entry) => entry.cell.kind === "value" && entry.cell.value !== null);
    if (scored.length < 2) continue;

    const best = Math.min(...scored.map((entry) => entry.cell.value as number));
    const leaders = scored.filter((entry) => entry.cell.value === best);
    if (leaders.length !== 1) continue;

    rowsCompared += 1;
    const solver = leaders[0].solver;
    wins.set(solver, (wins.get(solver) ?? 0) + 1);
  }

  if (rowsCompared === 0) return null;
  const ranked = [...wins.entries()].sort((a, b) => b[1] - a[1]);
  // A draw between two solvers on the same number of rows names no winner.
  if (ranked.length > 1 && ranked[0][1] === ranked[1][1]) return null;
  return { solver: ranked[0][0], wins: ranked[0][1], rowsCompared };
}

/**
 * The dataset that cost the most, by the slowest solver that finished it.
 *
 * The slowest column rather than the sum: a row where one solver gave up at the
 * time limit and three were quick is not a harder row than one where all four
 * took that long, and the sum would say it was.
 */
export function hardestRow(rows: ComparisonMatrixRow[]): ComparisonMatrixRow | null {
  let hardest: ComparisonMatrixRow | null = null;
  let worst = -1;

  for (const row of rows) {
    const times = row.results
      .map((result) => cellOf(result, "time"))
      .filter((cell) => cell.kind === "value" && cell.value !== null)
      .map((cell) => cell.value as number);
    if (times.length === 0) continue;
    const slowest = Math.max(...times);
    if (slowest > worst) {
      worst = slowest;
      hardest = row;
    }
  }
  return hardest;
}

/** Lifecycle states with something still to happen. */
const LIVE_STATUSES = new Set(["pending", "running"]);

/**
 * Whether the page should keep asking for a fresher grid.
 *
 * Not simply "is the matrix running". Stopping it marks every unstarted row
 * cancelled at once, but the solve already inside a solver cannot be
 * interrupted: the worker finishes it and writes its verdict a few seconds
 * later. A cell without a verdict keeps the polling alive on its own.
 */
export function shouldKeepPollingMatrix(
  batch: { status: string; rows: ComparisonMatrixRow[] } | null,
): boolean {
  if (!batch) return false;
  if (LIVE_STATUSES.has(batch.status)) return true;
  return batch.rows.some((row) => row.results.some((cell) => LIVE_STATUSES.has(cell.status)));
}

/** Whether there is still something to stop. */
export function canStopMatrix(batch: { status: string } | null): boolean {
  return batch !== null && LIVE_STATUSES.has(batch.status);
}
