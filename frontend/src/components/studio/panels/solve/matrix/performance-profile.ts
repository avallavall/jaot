/**
 * Dolan–Moré performance profile for a solver matrix.
 *
 * The table answers "which solver won this dataset". It cannot answer "which
 * solver should I pick by default", because that is a question about the whole
 * set of datasets and a reader has to do the division in their head, row by row.
 *
 * The profile does that division. For every dataset it divides each solver's
 * time by the best time on that dataset, giving a ratio of 1 for the winner and
 * "2x slower than the winner" for the rest. Then, for each factor t on the x
 * axis, it plots the fraction of datasets a solver got within t times the best.
 * The curve at t = 1 is how often that solver won outright; where the curve
 * flattens is the fraction of datasets it can finish at all.
 *
 * Two rules keep it honest, and both cost curves that would otherwise look
 * better than the solver is:
 *
 *  - Only a PROVEN answer counts as solved. A run that hit the time limit with
 *    a solution in hand did not solve the dataset, it ran out of clock, so it
 *    never enters a ratio. Counting it would reward giving up early.
 *  - A dataset nobody solved is dropped from every solver's denominator. It
 *    tells you nothing about a choice between them, and leaving it in drags
 *    every curve down by the same amount, which changes the axis and not the
 *    answer.
 */
import type { ComparisonMatrixRow, ComparisonSolverResult } from "@/lib/types";

/**
 * The number of datasets below which the profile says nothing.
 *
 * With four datasets every curve is a staircase of 25% steps, and a single
 * dataset changing hands moves a solver a quarter of the way up the chart. That
 * reads as a difference between solvers when it is a difference of one run.
 */
export const MIN_INSTANCES_FOR_PROFILE = 5;

/** One solver's step curve: the fraction solved within each factor. */
export interface ProfileCurve {
  solver: string;
  /** Points in ascending tau, already deduplicated. */
  points: { tau: number; fraction: number }[];
  /** How often this solver was the fastest of those that proved an answer. */
  wins: number;
  /** Datasets this solver proved an answer for. */
  solved: number;
}

export interface PerformanceProfile {
  curves: ProfileCurve[];
  /** Datasets that at least one solver proved. The denominator of every curve. */
  instances: number;
  /** The right-hand end of the axis. Always >= 1. */
  maxRatio: number;
  /** Solvers that proved nothing, named rather than drawn as a flat line at 0. */
  neverSolved: string[];
}

/**
 * Did this run prove its answer?
 *
 * "optimal", "infeasible" and "unbounded" are all proofs — the solver settled
 * the question. "feasible" is not: it means the clock ran out with a solution
 * that was never shown to be the best one.
 */
function proved(result: ComparisonSolverResult): boolean {
  if (result.status !== "completed") return false;
  return (
    result.solver_status === "optimal" ||
    result.solver_status === "infeasible" ||
    result.solver_status === "unbounded"
  );
}

/**
 * The seconds a ratio divides.
 *
 * Wall time, not the solver's own search time: a solver that builds its model
 * slowly costs the user those seconds too, and two adapters do not agree on
 * where building ends and searching begins. Zero is floored to a millisecond so
 * a solve too fast to measure cannot divide the whole chart by nothing.
 */
function secondsOf(result: ComparisonSolverResult): number | null {
  const ms = result.wall_time_ms;
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  return Math.max(ms, 1) / 1000;
}

/**
 * Build the profile from the matrix rows.
 *
 * Returns null when there is nothing worth drawing: too few datasets, or fewer
 * than two solvers that ever proved anything.
 */
export function performanceProfile(
  rows: ComparisonMatrixRow[],
  solverNames: string[],
): PerformanceProfile | null {
  // ratios[solver] = the ratio per counted dataset, or null when it did not solve it
  const ratios = new Map<string, (number | null)[]>();
  for (const name of solverNames) ratios.set(name, []);

  let instances = 0;
  const wins = new Map<string, number>();

  for (const row of rows) {
    const times = new Map<string, number>();
    for (const result of row.results) {
      if (!proved(result)) continue;
      const s = secondsOf(result);
      if (s == null) continue;
      times.set(result.solver_name, s);
    }
    if (times.size === 0) continue; // nobody solved it: it separates nothing

    instances += 1;
    const best = Math.min(...times.values());
    for (const name of solverNames) {
      const t = times.get(name);
      ratios.get(name)?.push(t === undefined ? null : t / best);
    }
    for (const [name, t] of times) {
      if (t === best) wins.set(name, (wins.get(name) ?? 0) + 1);
    }
  }

  if (instances < MIN_INSTANCES_FOR_PROFILE) return null;

  const finite: number[] = [];
  for (const list of ratios.values()) {
    for (const r of list) if (r != null) finite.push(r);
  }
  // The axis ends a little past the worst real ratio, so the last step is
  // visible instead of sitting on the frame.
  const maxRatio = Math.max(1, ...finite) * 1.15;

  const curves: ProfileCurve[] = [];
  const neverSolved: string[] = [];

  for (const name of solverNames) {
    const list = ratios.get(name) ?? [];
    const solved = list.filter((r): r is number => r != null).sort((a, b) => a - b);
    if (solved.length === 0) {
      neverSolved.push(name);
      continue;
    }
    // A step curve: it rises at each ratio and holds flat until the next.
    const points: { tau: number; fraction: number }[] = [{ tau: 1, fraction: 0 }];
    let count = 0;
    for (const r of solved) {
      count += 1;
      const tau = Math.max(1, r);
      const fraction = count / instances;
      const last = points[points.length - 1];
      if (last.tau === tau) {
        last.fraction = fraction;
      } else {
        // Hold the previous height right up to this ratio, then step up.
        points.push({ tau, fraction: last.fraction });
        points.push({ tau, fraction });
      }
    }
    // Carry the final height to the end of the axis: a curve that stops early
    // reads as a solver that got worse, when it simply solved nothing more.
    points.push({ tau: maxRatio, fraction: points[points.length - 1].fraction });
    curves.push({ solver: name, points, wins: wins.get(name) ?? 0, solved: solved.length });
  }

  if (curves.length < 2) return null;

  return { curves, instances, maxRatio, neverSolved };
}

/**
 * The curves resampled onto one shared ladder of tau values.
 *
 * Recharts draws one row per x value, so every curve has to be evaluated at the
 * same points or the lines break wherever a solver has no ratio of its own.
 */
export function profileSeries(
  profile: PerformanceProfile,
): { tau: number; [solver: string]: number }[] {
  const taus = new Set<number>([1, profile.maxRatio]);
  for (const curve of profile.curves) {
    for (const p of curve.points) taus.add(p.tau);
  }
  const ladder = [...taus].sort((a, b) => a - b);

  return ladder.map((tau) => {
    const point: { tau: number; [solver: string]: number } = { tau };
    for (const curve of profile.curves) {
      // The height of a step curve at tau is the last step at or below it.
      let value = 0;
      for (const p of curve.points) {
        if (p.tau <= tau) value = p.fraction;
        else break;
      }
      point[curve.solver] = value;
    }
    return point;
  });
}
