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
 * Map a live event to the `ProgressPoint` shape (`extractProgressHistory`'s).
 * Returns null when there is no finite objective yet, so callers can simply
 * `.filter(Boolean)`.
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
  /** How many times the best objective improved. */
  incumbents: number;
  /** Seconds since the solve started, or the run's own time once it is over. */
  elapsedSeconds: number | null;
}

/** The figures a finished run reports, which replace the live ones. */
export interface FinalFigures {
  objective_value?: number | null;
  gap?: number | null;
  nodes?: number | null;
  solve_time_seconds?: number | null;
}

/**
 * How many times the best objective changed. A point is not always an incumbent:
 * JAOS also sends a point when only the bound moved, and counting points put
 * "7 incumbents" under a best objective that never left 450.
 */
function countIncumbents(points: ProgressPoint[]): number {
  let count = 0;
  let previous: number | null = null;
  for (const point of points) {
    if (previous === null || point.objective !== previous) count += 1;
    previous = point.objective;
  }
  return count;
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Derive the headline metrics from the accumulated chart points + the last raw event
 * (the raw event carries `node`, which is not part of the chart `ProgressPoint`).
 *
 * While the run is live, `liveElapsedSeconds` is the page's own clock since the
 * start: the last point's time froze between events (30.8 s on a 60 s run). Once
 * the run is over, `final` holds what it returned, and those figures win.
 */
export function computeMetrics(
  points: ProgressPoint[],
  lastEvent: SolveProgressEvent | null,
  final: FinalFigures | null = null,
  liveElapsedSeconds: number | null = null,
): LiveSolveMetrics {
  const last = points.length > 0 ? points[points.length - 1] : null;
  const eventNodes = lastEvent && typeof lastEvent.node === "number" ? lastEvent.node : null;
  return {
    bestObjective: finite(final?.objective_value) ?? (last ? last.objective : null),
    gap: finite(final?.gap) ?? (last ? last.gap : null),
    nodes: finite(final?.nodes) ?? eventNodes,
    incumbents: countIncumbents(points),
    elapsedSeconds:
      finite(final?.solve_time_seconds) ??
      liveElapsedSeconds ??
      (last ? last.timestamp / 1000 : null),
  };
}
