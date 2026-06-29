import type { OptimizationProblem } from "@/lib/types";

/**
 * The visual canvas renders one node per variable and per constraint. Past a few
 * hundred nodes React Flow gets sluggish; in the tens of thousands (e.g. an
 * imported large MILP — a 200×200 assignment model is ~40k binary vars) deriving
 * and laying out the nodes locks the main thread and the tab never recovers.
 *
 * Above this many model elements the studio SKIPS the canvas entirely and works
 * from the canonical model directly — the model stays fully solvable and (once
 * the text Editor lens lands) editable; only the visual lens is withheld.
 */
export const CANVAS_SCALE_CAP = 800;

/** variables + constraints — a cheap proxy for the canvas node count. */
export function modelElementCount(problem: OptimizationProblem | null | undefined): number {
  if (!problem) return 0;
  const v = Array.isArray(problem.variables) ? problem.variables.length : 0;
  const c = Array.isArray(problem.constraints) ? problem.constraints.length : 0;
  return v + c;
}

/** True when the model is too large to render on the visual canvas safely. */
export function exceedsCanvasScale(problem: OptimizationProblem | null | undefined): boolean {
  return modelElementCount(problem) > CANVAS_SCALE_CAP;
}
