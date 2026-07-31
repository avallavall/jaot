import type { OptimizationProblem } from "@/lib/types";
import { parseLinearSide, parseLinearConstraint } from "@/lib/builder/linear";

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

/**
 * Whether the visual canvas can hold this model EXACTLY — every constraint a
 * linear `terms OP rhs` over declared variables, the objective a linear
 * expression with no constant. When it can't (an assistant/imported model with
 * nonlinear pieces, functions, parentheses…), the canvas must be withheld like
 * the too-large case: rendering a partial view that later serializes back over
 * the canonical model would silently corrupt it (that is exactly how a Treasury
 * model's balance constraints once became `0 <= 0` rows in production).
 */
export function canvasCanRepresentModel(
  problem: OptimizationProblem | null | undefined
): boolean {
  if (!problem) return true;
  const declared = new Set((problem.variables ?? []).map((v) => v.name));
  if (problem.objective) {
    const objective = parseLinearSide(problem.objective.expression);
    if (
      objective === null ||
      Math.abs(objective.constant) > 1e-9 || // no edge can carry a constant
      objective.terms.some((t) => !declared.has(t.varName))
    ) {
      return false;
    }
  }
  for (const constraint of problem.constraints ?? []) {
    const parsed = parseLinearConstraint(constraint.expression);
    if (parsed === null || parsed.terms.some((t) => !declared.has(t.varName))) {
      return false;
    }
  }
  return true;
}
