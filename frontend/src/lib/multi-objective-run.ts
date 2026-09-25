import type { MultiObjectiveResult } from "@/lib/types";

/**
 * The `solver_status` the server stores on a multi-objective run that found a
 * front (app/schemas/optimization.py MULTI_OBJECTIVE_STATUS). A front is many
 * answers, so no single-solve verdict describes it.
 */
export const MULTI_OBJECTIVE_STATUS = "pareto_front";

/**
 * The Pareto front a stored run holds, or null for an ordinary solve.
 *
 * A multi-objective run keeps its front under `result_data.multi_objective`
 * and leaves every single-solve field empty. The execution page read only
 * those fields, so it showed "Optimal solution proven" over a row of dashes
 * and never the points. Runs saved before the status existed are stored as
 * "optimal", which is why the payload decides, not the status.
 */
export function readMultiObjective(resultData: unknown): MultiObjectiveResult | null {
  if (!resultData || typeof resultData !== "object") return null;
  const front = (resultData as { multi_objective?: unknown }).multi_objective;
  if (!front || typeof front !== "object") return null;
  const points = (front as { pareto_points?: unknown }).pareto_points;
  if (!Array.isArray(points)) return null;
  return front as MultiObjectiveResult;
}
