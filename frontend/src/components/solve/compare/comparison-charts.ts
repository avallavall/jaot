import type { ComparisonDetail, ComparisonSolverResult } from "@/lib/types";

/** Verdicts that mean the solver actually ran and produced numbers to draw. */
const RAN = new Set(["optimal", "feasible", "infeasible", "unbounded", "time_limit"]);

/** Verdicts that come with an objective worth putting on an axis. */
const ANSWERED = new Set(["optimal", "feasible", "time_limit"]);

/** The smallest time a logarithmic axis can show. A solve too fast to measure
 * is floored to this rather than dropped: it did happen, and it was fastest. */
export const LOG_FLOOR_SECONDS = 0.001;

/** Below two bars there is nothing to compare, and a chart of one is a number
 * with decoration around it. */
export const MIN_BARS = 2;

function ranRows(comparison: ComparisonDetail): ComparisonSolverResult[] {
  return comparison.results.filter(
    (row) => row.solver_status !== null && RAN.has(row.solver_status),
  );
}

// ──────────────────────────────────────────────────────────────
// How long each solver took
// ──────────────────────────────────────────────────────────────

export interface TimeBar {
  solver: string;
  seconds: number;
  /** How many times the fastest solver's time this is. 1 for the fastest. */
  ratio: number;
}

/** Total wall time per solver, fastest first. */
export function timeBars(comparison: ComparisonDetail): TimeBar[] {
  const timed = ranRows(comparison)
    .filter((row) => row.wall_time_ms !== null)
    .map((row) => ({
      solver: row.solver_name,
      // Floored here, not only on the axis. A solve under a millisecond rounds
      // to zero, and zero has no place on a logarithmic scale: the bar comes out
      // as NaN and the fastest solver disappears from its own chart.
      seconds: Math.max((row.wall_time_ms as number) / 1000, LOG_FLOOR_SECONDS),
    }))
    .sort((a, b) => a.seconds - b.seconds);
  if (timed.length < MIN_BARS) return [];

  const fastest = timed[0].seconds;
  return timed.map((bar) => ({
    ...bar,
    ratio: fastest > 0 ? bar.seconds / fastest : 1,
  }));
}

/**
 * A log axis covering these values, rounded out to whole powers of ten.
 *
 * The axis is logarithmic because a comparison routinely spans two orders of
 * magnitude — GLPK can take a hundred times what SCIP takes — and on a linear
 * axis every other bar is then pressed flat against zero and says nothing.
 *
 * Zero has no place on a log axis, so a solve too fast to measure is floored at
 * one millisecond rather than dropped: it did happen, and it was the fastest.
 */
export function logDomain(values: number[]): [number, number] {
  const positive = values.map((value) => Math.max(value, LOG_FLOOR_SECONDS));
  if (positive.length === 0) return [LOG_FLOOR_SECONDS, 1];
  const smallest = Math.min(...positive);
  let low = Math.pow(10, Math.floor(Math.log10(smallest)));
  // A bar starts at the axis low and ends at its value, so a value sitting
  // exactly ON the low has no length: it is drawn as nothing and its label has
  // nowhere to go. That is what happened to any solve at or under a
  // millisecond, since the floor is itself a power of ten — the solver badged
  // "Fastest" was the one missing from the chart of who was fastest. Only drop
  // a decade when they coincide, so a domain like [0.4, 37] still rounds out to
  // [0.1, 100] rather than wasting a decade on every chart.
  if (low === smallest) low /= 10;
  const high = Math.pow(10, Math.ceil(Math.log10(Math.max(...positive))));
  // A single decade would put every bar on the same tick.
  return [low, high > low ? high : low * 10];
}

// ──────────────────────────────────────────────────────────────
// How much room each solver had left
// ──────────────────────────────────────────────────────────────

export interface BoundBar {
  solver: string;
  /** Where the bar starts on the shared axis. */
  low: number;
  /** How long it is: the distance still to close. Zero when proven. */
  span: number;
  objective: number;
  bound: number;
  /** The two ends met: this solver proved its answer. */
  proven: boolean;
}

/** Whether this solver reported both the answer and the bound the chart needs. */
function hasBothEnds(row: ComparisonSolverResult): boolean {
  return (
    row.solver_status !== null &&
    ANSWERED.has(row.solver_status) &&
    row.objective_value !== null &&
    row.dual_bound !== null
  );
}

/**
 * The distance between what each solver found and what it proved possible.
 *
 * This is the chart a comparison under a time limit is really about. The table
 * puts the objective in one column and the bound in another and leaves the
 * reader to imagine the distance between them; drawn on one shared axis, a
 * solver that stopped a long way short is obvious next to one that closed.
 */
export function boundBars(comparison: ComparisonDetail): BoundBar[] {
  const bars = ranRows(comparison)
    .filter(hasBothEnds)
    .map((row) => {
      const objective = row.objective_value as number;
      const bound = row.dual_bound as number;
      const span = Math.abs(objective - bound);
      return {
        solver: row.solver_name,
        low: Math.min(objective, bound),
        span,
        objective,
        bound,
        // Exactly equal, not "close": a gap tolerance already decided what close
        // enough means, and it is reported as the gap in its own column.
        proven: span === 0,
      };
    });
  return bars.length < MIN_BARS ? [] : bars;
}

/** Why a solver that ran is missing from the bound chart. */
export interface BoundOmission {
  solver: string;
  /** "noAnswer" when it reported no objective, "noBound" when it reported the
   * objective but nothing about how good it is. */
  reason: "noAnswer" | "noBound";
}

/**
 * Solvers that ran but are not in the bound chart, because they never reported
 * both ends.
 *
 * A solver that vanishes from a chart is read as a solver that was not asked,
 * which is the one thing a comparison must never suggest. The chart names them
 * underneath instead.
 *
 * The two reasons are kept apart because the line said "no answer reported"
 * under a table row that showed the answer. A solver that found the optimum and
 * reported no bound is doing neither of the things that sentence describes.
 */
export function boundOmissions(comparison: ComparisonDetail): BoundOmission[] {
  return ranRows(comparison)
    .filter((row) => !hasBothEnds(row))
    .map((row) => ({
      solver: row.solver_name,
      reason:
        row.objective_value === null || row.objective_value === undefined
          ? ("noAnswer" as const)
          : ("noBound" as const),
    }));
}

/** A linear axis covering every bar, with a tenth of the span as breathing room. */
export function boundDomain(bars: BoundBar[]): [number, number] {
  if (bars.length === 0) return [0, 1];
  const low = Math.min(...bars.map((bar) => bar.low));
  const high = Math.max(...bars.map((bar) => bar.low + bar.span));
  if (high === low) return [low - 1, high + 1];
  const margin = (high - low) / 10;
  return [low - margin, high + margin];
}

// ──────────────────────────────────────────────────────────────
// Where the seconds went
// ──────────────────────────────────────────────────────────────

export interface SplitBar {
  solver: string;
  /** The solver's own measure of the search. */
  search: number;
  /** Everything else in the wall time: translating the problem into that
   * solver's own model. That part is JAOT's cost, not the solver's. */
  build: number;
}

/** How much of the wait must be model building before the split is worth a chart. */
export const MIN_BUILD_SHARE = 0.05;

/** How far past the wall time a search may land before it stops being rounding.
 * Both numbers are rounded to whole milliseconds, so one millisecond either way
 * says nothing. */
export const CLOCK_ALLOWANCE_SECONDS = 0.002;

/**
 * The search time this row can be shown with: the solver's own measure, never
 * longer than the wall time that contains it.
 *
 * The two come from different clocks, so the search can land past the wall.
 * The chart clamped and the table did not, so the same row read 5.26 s in one
 * place and 3.39 s in the other with nothing saying they differed. Both read
 * this now.
 */
export function searchSecondsOf(row: ComparisonSolverResult): number | null {
  const search = row.solver_time_seconds;
  if (search === null || search === undefined) return null;
  if (row.wall_time_ms === null || row.wall_time_ms === undefined) return search;
  return Math.min(search, row.wall_time_ms / 1000);
}

/**
 * Seconds the raw search overran the wall time by, or null when it did not.
 *
 * A clamped number on its own would quietly rewrite what was measured. Rows
 * recorded before the adapters moved to a monotonic clock still carry the
 * disagreement, and it is worth a line rather than a silent correction.
 */
export function searchOverstatedBy(row: ComparisonSolverResult): number | null {
  const search = row.solver_time_seconds;
  if (search === null || search === undefined) return null;
  if (row.wall_time_ms === null || row.wall_time_ms === undefined) return null;
  const excess = search - row.wall_time_ms / 1000;
  return excess > CLOCK_ALLOWANCE_SECONDS ? excess : null;
}

/**
 * Search time against the rest, per solver.
 *
 * On a model of twenty thousand variables the building is a real share of the
 * wait, and it is ours rather than the solver's. Two columns of numbers hide
 * that; one stacked bar does not.
 *
 * Drawn only when some solver actually spent a share of its wait building. When
 * every solver went almost straight into the search — which is the normal case
 * on a small model — this chart is the time chart again with a linear axis, and
 * a second chart saying the same thing is noise.
 */
export function splitBars(comparison: ComparisonDetail): SplitBar[] {
  const bars = ranRows(comparison)
    .filter((row) => row.wall_time_ms !== null && row.solver_time_seconds !== null)
    .map((row) => {
      const wall = (row.wall_time_ms as number) / 1000;
      const search = searchSecondsOf(row) as number;
      return { solver: row.solver_name, search, build: Math.max(0, wall - search) };
    })
    .sort((a, b) => a.search + a.build - (b.search + b.build));
  if (bars.length < MIN_BARS) return [];

  const worthDrawing = bars.some((bar) => {
    const total = bar.search + bar.build;
    return total > 0 && bar.build / total >= MIN_BUILD_SHARE;
  });
  return worthDrawing ? bars : [];
}
