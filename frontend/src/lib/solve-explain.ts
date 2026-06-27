import type { ModelExecution } from "@/lib/types";

export interface ExplainState {
  /** Resolved solver status. Prefers the execution's top-level `solver_status`
   *  and falls back to `result_data.status`, which is the field present on async
   *  runs whose inline result has no top-level solver_status. */
  solverStatus: string | null;
  /** The solve was infeasible — the infeasibility explainer applies. */
  isInfeasible: boolean;
  /** The solve produced variable values — there is a solution to explain. */
  hasSolution: boolean;
  /** The solution can be explained (completed AND optimal/feasible). */
  canExplainSolution: boolean;
}

/**
 * Decide which LLM result-explainer (if any) applies to a solve result.
 *
 * Single source of truth for the run page's explainer gating. Reads
 * `result_data.status` (the OptimizationResult field — NOT `solver_status`,
 * which only exists at the top level of an execution record) so the gating is
 * correct for both sync and async solves.
 */
export function deriveExplainState(result: ModelExecution | null): ExplainState {
  const resultData = result?.result_data;
  const solverStatus = result?.solver_status ?? resultData?.status ?? null;
  const isInfeasible = solverStatus === "infeasible";
  const hasSolution = (resultData?.variables?.length ?? 0) > 0;
  const canExplainSolution =
    result?.status === "completed" &&
    (solverStatus === "optimal" || solverStatus === "feasible");
  return { solverStatus, isInfeasible, hasSolution, canExplainSolution };
}
