import type { ProgressPoint } from "@/lib/result-utils";

/**
 * A live `solve_progress` event streamed per new incumbent (mirrors the backend
 * ProgressPoint published on each SCIP BESTSOLFOUND).
 */
export interface SolveProgressEvent {
  iteration?: number;
  node?: number;
  objective?: number;
  primal_bound?: number;
  dual_bound?: number | null;
  gap?: number;
  elapsed_seconds?: number;
}

/**
 * Map a live event to the chart's `ProgressPoint` shape (the one `GapConvergenceChart`
 * + `extractProgressHistory` use). Returns null when there is no finite objective yet,
 * so callers can simply `.filter(Boolean)`.
 */
export function toProgressPoint(
  event: SolveProgressEvent,
  index: number,
): ProgressPoint | null {
  const objective = event.objective ?? event.primal_bound;
  if (typeof objective !== "number" || !Number.isFinite(objective)) {
    return null;
  }
  return {
    iteration: typeof event.iteration === "number" ? event.iteration : index + 1,
    objective,
    gap: typeof event.gap === "number" && Number.isFinite(event.gap) ? event.gap : 0,
    timestamp:
      typeof event.elapsed_seconds === "number" ? event.elapsed_seconds * 1000 : index,
  };
}

export interface LiveSolveMetrics {
  /** Latest incumbent objective. */
  bestObjective: number | null;
  /** Latest MIP gap as a fraction (0.05 = 5%). */
  gap: number | null;
  /** Branch-and-bound nodes explored at the last event. */
  nodes: number | null;
  /** Number of incumbents found so far (chart points). */
  incumbents: number;
  /** Wall time of the last incumbent, in seconds. */
  elapsedSeconds: number | null;
}

/**
 * Derive the headline metrics from the accumulated chart points + the last raw event
 * (the raw event carries `node`, which is not part of the chart `ProgressPoint`).
 */
export function computeMetrics(
  points: ProgressPoint[],
  lastEvent: SolveProgressEvent | null,
): LiveSolveMetrics {
  const last = points.length > 0 ? points[points.length - 1] : null;
  return {
    bestObjective: last ? last.objective : null,
    gap: last ? last.gap : null,
    nodes:
      lastEvent && typeof lastEvent.node === "number" ? lastEvent.node : null,
    incumbents: points.length,
    elapsedSeconds: last ? last.timestamp / 1000 : null,
  };
}
