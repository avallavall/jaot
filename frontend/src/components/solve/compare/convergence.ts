/**
 * The convergence chart: how each solver closed its gap, second by second.
 *
 * The table says where a solver ended up. It cannot say how it got there, and
 * that is what separates two solvers that report the same answer in the same
 * time: one had it after half a second and spent the rest proving it, the other
 * found it at the buzzer.
 *
 * What is plotted is the GAP, not the objective, and that was decided by
 * measuring. A 220-item knapsack run on SCIP and CBC opens with a relaxation of
 * 11.3 million, takes a trivial first answer of 0, and then spends the whole
 * search between 5.664 and 5.665 million. On an axis of objective values wide
 * enough to hold 0 and 11.3 million, that search is one flat line — a chart
 * whose only claim is how the gap closed, showing no gap closing. The gap is
 * dimensionless, it falls from 100% to 0.0005% on that same instance, and a
 * logarithmic axis shows every decade of it.
 *
 * Only two of the five solvers can answer at all, and saying so is the point:
 *
 *  - SCIP publishes a snapshot per incumbent, with the clock. It is drawn.
 *  - CBC prints the same thing in its log, with the clock. It is drawn.
 *  - GLPK prints a trace with no clock in it, only an iteration number. There is
 *    no honest way to put that on an axis of seconds beside the other two.
 *  - HiGHS says nothing at all while it searches.
 *
 * A solver that ran and reported nothing is named under the chart. Left out
 * silently it reads as "not asked for", which is the one thing it is not.
 */
import type { ComparisonSolverResult, ProgressTracePoint } from "@/lib/types";

/** One solver's line: what fraction it still had to close, and when. */
export interface ConvergenceLine {
  solver: string;
  points: { seconds: number; gap: number }[];
  /** The second it first reached a gap of zero, or null if it never did. */
  provedAt: number | null;
}

export interface ConvergenceData {
  lines: ConvergenceLine[];
  /** Solvers that ran and reported nothing usable while they searched. */
  silent: string[];
  /** The last second any line reaches. */
  maxSeconds: number;
  /** The log axis, low to high. Never contains zero: a log axis has no zero. */
  domain: [number, number];
  /** True when at least one solver reached zero and is drawn on the floor. */
  anyProved: boolean;
}

/** Did this solver actually run? */
function ran(result: ComparisonSolverResult): boolean {
  return result.status === "completed" && result.solver_status !== "unsupported";
}

/**
 * The gap at one snapshot, as a fraction, or null when there is not one.
 *
 * The solver's own number is preferred: it is what its log printed and what the
 * table shows. Computing it from the two bounds is the fallback for a trace that
 * carries them and not the ratio.
 *
 * An objective of exactly zero has no relative gap, and that is not a corner
 * case here. On a maximization "take nothing" is the trivial first answer and
 * SCIP reports it. Dividing by it gives infinity, and calling it 100% would
 * claim the solver knew something it did not.
 */
export function gapOf(point: ProgressTracePoint): number | null {
  if (point.gap != null && Number.isFinite(point.gap) && point.gap >= 0) return point.gap;
  const bound = point.dual_bound;
  if (bound == null || !Number.isFinite(bound)) return null;
  if (!Number.isFinite(point.objective) || point.objective === 0) return null;
  return Math.abs(point.objective - bound) / Math.abs(point.objective);
}

/** A trace sorted by the clock, with the snapshots that cannot be drawn removed. */
function usable(points: ProgressTracePoint[]): { seconds: number; gap: number }[] {
  return points
    .filter((p) => Number.isFinite(p.elapsed_seconds) && p.elapsed_seconds >= 0)
    .map((p) => ({ seconds: p.elapsed_seconds, gap: gapOf(p) }))
    .filter((p): p is { seconds: number; gap: number } => p.gap != null)
    .sort((a, b) => a.seconds - b.seconds);
}

/**
 * Build the chart's data from the comparison's rows.
 *
 * Returns null when fewer than two solvers have a usable trace. One line is not
 * a comparison, and the whole point is putting two searches on one clock.
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
    const proved = points.find((p) => p.gap === 0);
    lines.push({ solver: result.solver_name, points, provedAt: proved?.seconds ?? null });
  }

  if (lines.length < 2) return null;

  const maxSeconds = Math.max(...lines.map((l) => l.points[l.points.length - 1].seconds));
  const positives = lines.flatMap((l) => l.points.map((p) => p.gap)).filter((g) => g > 0);
  const anyProved = lines.some((l) => l.provedAt !== null);

  // A log axis cannot show zero. The floor sits a decade below the smallest gap
  // any solver actually reached, so a search that closed completely lands on the
  // bottom line with room to be seen getting there.
  const smallest = positives.length > 0 ? Math.min(...positives) : 1e-6;
  const largest = positives.length > 0 ? Math.max(...positives) : 1;
  const floor = Math.max(smallest / 10, 1e-12);
  return { lines, silent, maxSeconds, domain: [floor, largest], anyProved };
}

/**
 * The lines resampled onto one shared ladder of seconds.
 *
 * Recharts draws one row per x value, so two solvers that reported at different
 * moments have to be evaluated at the same instants. A solver's value at time t
 * is the last thing it reported at or before t, which is what it actually held
 * then. Before its first report it has nothing, and the key is left out so the
 * line starts where the search did instead of at the top of the axis.
 *
 * A gap of exactly zero is drawn on the floor of the log axis, because a log
 * axis has no zero. The chart says in words that the floor means proved.
 */
export function convergenceSeries(
  data: ConvergenceData,
): Record<string, number | undefined>[] {
  const instants = new Set<number>();
  for (const line of data.lines) {
    for (const p of line.points) instants.add(p.seconds);
  }
  const ladder = [...instants].sort((a, b) => a - b);
  const [floor] = data.domain;

  return ladder.map((seconds) => {
    const row: Record<string, number | undefined> = { seconds };
    for (const line of data.lines) {
      let held: number | null = null;
      for (const p of line.points) {
        if (p.seconds <= seconds) held = p.gap;
        else break;
      }
      if (held === null) continue; // this solver had not reported yet
      row[line.solver] = held === 0 ? floor : held;
    }
    return row;
  });
}
