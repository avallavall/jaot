import type { OptimizationProblem } from "@/lib/types";

export type SolveBlock = "noVariables" | "noObjective";

/**
 * Why a solve is blocked, or null when the model is solvable. Pure (unit-tested):
 * mirrors the builder's preconditions on the canonical model — at least one
 * variable and a non-empty objective expression.
 */
export function solveBlockedReason(problem: OptimizationProblem): SolveBlock | null {
  if (!problem.variables || problem.variables.length === 0) return "noVariables";
  if (!problem.objective?.expression?.trim()) return "noObjective";
  return null;
}
