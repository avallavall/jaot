/**
 * Work against time: how much searching each solver did for the seconds it took.
 *
 * The time chart says who was slower. It cannot say why, and there are only two
 * answers: the slower solver explored more of the tree, or each piece of tree
 * cost it more. Work count and seconds together separate those two, and neither
 * number on its own does.
 *
 * Every solver gets its own panel and its own vertical scale, and that is the
 * whole design. A node in one solver is not a node in another: they presolve
 * differently, add different cuts and end up searching a different tree, so a
 * shared axis of node counts invites exactly the comparison the table already
 * warns against. What every panel does share is the clock, because seconds mean
 * the same thing to all of them.
 *
 * A solver that ran and reported no counters is named under the chart. Left out
 * silently it reads as "not asked for", which is the one thing it is not.
 */
import type { ComparisonSolverResult, ProgressTracePoint } from "@/lib/types";

import { LOG_FLOOR_SECONDS, MIN_BARS, ranRows, searchSecondsOf } from "./comparison-charts";

/** What a solver counts its search in. */
export type WorkUnit = "nodes" | "iterations";

export interface WorkPoint {
  seconds: number;
  work: number;
}

export interface WorkPanel {
  solver: string;
  unit: WorkUnit;
  /** The search as it was reported: work done by each second. Empty when the
   * solver only handed over its final count. */
  points: WorkPoint[];
  /** The final counter, the same number the table's column shows. */
  total: number;
  /** How long the search took. The panel's point sits here on the shared axis. */
  seconds: number;
  /** Work per second: the half of the answer that says whether the tree was
   * bigger or the nodes were dearer. */
  perSecond: number;
}

/** Why a solver that ran has no panel. */
export interface WorkOmission {
  solver: string;
  /** "noCount" when it counted neither nodes nor iterations, "noClock" when it
   * counted work but reported no time to divide it by. */
  reason: "noCount" | "noClock";
}

export interface WorkData {
  panels: WorkPanel[];
  omitted: WorkOmission[];
  /** The right edge every panel shares. */
  maxSeconds: number;
  /** At least one panel is a single dot, which needs a sentence of its own. */
  anyEndOnly: boolean;
}

/**
 * The measure this solver counted its search in, and how much of it there was.
 *
 * Nodes come first because on a mixed-integer model the tree is what the search
 * actually did; the LP iterations are the work inside those nodes. On a linear
 * program there is no tree at all and nobody reports nodes, so iterations are
 * then the only measure there is.
 */
export function workOf(row: ComparisonSolverResult): { unit: WorkUnit; total: number } | null {
  if (row.nodes != null && Number.isFinite(row.nodes) && row.nodes > 0) {
    return { unit: "nodes", total: row.nodes };
  }
  if (row.iterations != null && Number.isFinite(row.iterations) && row.iterations > 0) {
    return { unit: "iterations", total: row.iterations };
  }
  return null;
}

/**
 * A trace's node numbers made cumulative across the restarts CBC hides in them.
 *
 * CBC counts nodes from zero again every time it restarts its search, and it
 * does so mid-run. A real log from `cbc -log 2` on a knapsack this project
 * generated reads "After 150 nodes ... (0.15 seconds)" and then, one line later,
 * "After 0 nodes ... (0.16 seconds)", and finishes "took 200 nodes" — the 150
 * before the restart plus the 50 after it. Drawn as reported, the line saws back
 * to the floor and ends at a quarter of the number the table shows beside it.
 * Carrying the running total forward whenever the count drops rebuilds the 200.
 *
 * SCIP never restarts its count, so its trace comes through untouched.
 *
 * The trace's own `iteration` field is deliberately not used here. It is the
 * snapshot number — the adapters set it to the length of the list so far — and
 * drawing it as work would put a straight line on every panel.
 */
export function cumulativeWork(points: ProgressTracePoint[]): WorkPoint[] {
  const usable = points
    .filter(
      (point) =>
        point.node != null &&
        Number.isFinite(point.node) &&
        point.node >= 0 &&
        Number.isFinite(point.elapsed_seconds) &&
        point.elapsed_seconds >= 0,
    )
    .sort((a, b) => a.elapsed_seconds - b.elapsed_seconds);

  const out: WorkPoint[] = [];
  let carried = 0;
  let previous = 0;
  for (const point of usable) {
    const node = point.node as number;
    // A count that went backwards is a restart, never a solver undoing work.
    if (node < previous) carried += previous;
    previous = node;
    out.push({ seconds: point.elapsed_seconds, work: carried + node });
  }
  return out;
}

/**
 * The trace with the solver's final count appended.
 *
 * A trace stops at the last snapshot the solver published, and that is not the
 * end of the search. Driving a four-solver knapsack, CBC's own trace topped out
 * at 4,000 nodes beside a caption reading 4,727 — the curve appeared to
 * contradict the number printed above it. The closing point is added only when
 * it is genuinely later and genuinely no smaller, so the chart never invents a
 * rise the solver did not report.
 */
export function withFinalCount(points: WorkPoint[], seconds: number, total: number): WorkPoint[] {
  const last = points[points.length - 1];
  if (seconds <= last.seconds || total < last.work) return points;
  return [...points, { seconds, work: total }];
}

/**
 * Build the panels from the comparison's rows.
 *
 * Returns null below two panels. One panel compares nothing, and the point of
 * the chart is putting two searches on the same clock.
 */
export function workData(comparison: { results: ComparisonSolverResult[] }): WorkData | null {
  const panels: WorkPanel[] = [];
  const omitted: WorkOmission[] = [];

  for (const row of ranRows(comparison)) {
    const work = workOf(row);
    if (work === null) {
      omitted.push({ solver: row.solver_name, reason: "noCount" });
      continue;
    }
    const search = searchSecondsOf(row);
    const wall = row.wall_time_ms != null ? row.wall_time_ms / 1000 : null;
    const seconds = search ?? wall;
    if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
      omitted.push({ solver: row.solver_name, reason: "noClock" });
      continue;
    }

    // A trace of one point is the end point again, which the panel draws anyway.
    const traced = work.unit === "nodes" ? cumulativeWork(row.progress_history ?? []) : [];
    panels.push({
      solver: row.solver_name,
      unit: work.unit,
      points: traced.length >= 2 ? withFinalCount(traced, seconds, work.total) : [],
      total: work.total,
      seconds,
      // Floored, because a search too fast to measure rounds to zero seconds and
      // dividing by it reports an infinite rate. One millisecond is the same
      // floor the time chart uses.
      perSecond: work.total / Math.max(seconds, LOG_FLOOR_SECONDS),
    });
  }

  if (panels.length < MIN_BARS) return null;

  const ends = panels.map((panel) => {
    const last = panel.points.length > 0 ? panel.points[panel.points.length - 1].seconds : 0;
    return Math.max(panel.seconds, last);
  });
  return {
    panels,
    omitted,
    maxSeconds: Math.max(...ends, LOG_FLOOR_SECONDS),
    anyEndOnly: panels.some((panel) => panel.points.length === 0),
  };
}
