/**
 * The convergence chart: how each solver closed the gap, second by second.
 *
 * The table says where a solver ended up. It cannot say how it got there, and
 * that is what separates two solvers that report the same answer in the same
 * time: one had it after half a second and spent the rest proving it, the other
 * found it at the buzzer.
 *
 * Only two of the five solvers can answer, and pretending otherwise would be
 * the worse mistake:
 *
 *  - SCIP publishes a snapshot per incumbent, with the clock. It is drawn.
 *  - CBC prints the same thing in its log, with the clock. It is drawn.
 *  - GLPK prints a trace with no clock in it — only an iteration number. There
 *    is no honest way to put that on an axis of seconds beside the other two.
 *  - HiGHS says nothing at all while it searches.
 *
 * A solver with no trace is named under the chart. Left out silently it reads as
 * "not asked for", which is the one thing it is not.
 */
import type { ComparisonSolverResult, ProgressTracePoint } from "@/lib/types";

/** One solver's line: the incumbent, and the bound it had proved at the time. */
export interface ConvergenceLine {
  solver: string;
  points: { seconds: number; objective: number; bound: number | null }[];
}

/** Why a solver has no line. The chart says which, in words. */
export type NoTraceReason = "no_trace" | "not_run";

export interface ConvergenceData {
  lines: ConvergenceLine[];
  /** Solvers that ran and reported nothing while they searched. */
  silent: string[];
  /** The last second any line reaches. */
  maxSeconds: number;
}

/** Did this solver actually run to an answer? */
function ran(result: ComparisonSolverResult): boolean {
  return result.status === "completed" && result.solver_status !== "unsupported";
}

/**
 * A trace sorted by the clock, with the points that cannot be drawn removed.
 *
 * A point without a finite second has nowhere to sit on the axis, and a point
 * without a finite objective is the solver's own placeholder for "nothing yet".
 */
function usable(points: ProgressTracePoint[]): ProgressTracePoint[] {
  return points
    .filter(
      (p) =>
        Number.isFinite(p.elapsed_seconds) &&
        p.elapsed_seconds >= 0 &&
        Number.isFinite(p.objective),
    )
    .sort((a, b) => a.elapsed_seconds - b.elapsed_seconds);
}

/**
 * Build the chart's data from the comparison's rows.
 *
 * Returns null when fewer than two solvers have a trace. One line is not a
 * comparison, and the whole point of the chart is putting two searches on one
 * clock.
 */
export function convergenceData(results: ComparisonSolverResult[]): ConvergenceData | null {
  const lines: ConvergenceLine[] = [];
  const silent: string[] = [];

  for (const result of results) {
    if (!ran(result)) continue;
    const points = usable(result.progress_history ?? []);
    if (points.length < 2) {
      // One point is a dot, not a curve: it says where the solver finished,
      // which the table already says.
      silent.push(result.solver_name);
      continue;
    }
    lines.push({
      solver: result.solver_name,
      points: points.map((p) => ({
        seconds: p.elapsed_seconds,
        objective: p.objective,
        bound: p.dual_bound != null && Number.isFinite(p.dual_bound) ? p.dual_bound : null,
      })),
    });
  }

  if (lines.length < 2) return null;

  const maxSeconds = Math.max(
    ...lines.map((line) => line.points[line.points.length - 1].seconds),
  );
  return { lines, silent, maxSeconds };
}

/**
 * The lines resampled onto one shared ladder of seconds.
 *
 * Recharts draws one row per x value, so two solvers that reported at different
 * moments have to be evaluated at the same instants. A solver's value at time t
 * is the last thing it reported at or before t — which is what it actually held
 * at that moment. Before its first report it has nothing, and the key is left
 * out so the line starts where the search did instead of at zero.
 */
export function convergenceSeries(
  data: ConvergenceData,
): Record<string, number | undefined>[] {
  const instants = new Set<number>();
  for (const line of data.lines) {
    for (const p of line.points) instants.add(p.seconds);
  }
  const ladder = [...instants].sort((a, b) => a - b);

  return ladder.map((seconds) => {
    const point: Record<string, number | undefined> = { seconds };
    for (const line of data.lines) {
      let held: { objective: number; bound: number | null } | null = null;
      for (const p of line.points) {
        if (p.seconds <= seconds) held = p;
        else break;
      }
      if (held === null) continue; // this solver had not reported yet
      point[line.solver] = held.objective;
      if (held.bound != null) point[`${line.solver}__bound`] = held.bound;
    }
    return point;
  });
}
