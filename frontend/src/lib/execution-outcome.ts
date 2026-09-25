/** Solver verdicts that leave no plan to use. */
const NO_PLAN_VERDICTS = new Set(["infeasible", "unbounded", "error"]);

export interface RunOutcome {
  /** The job's state: pending, running, completed, failed, ... */
  status: string;
  /** What the solver concluded about the model, once the job has run. */
  solver_status?: string | null;
  objective_value?: number | null;
}

/**
 * Whether a run completed without a plan.
 *
 * `status` is the job's state. "completed" means the solver ran to the end.
 * That also covers an infeasible or unbounded model, a solver error, and a time
 * limit reached before any plan was found. The execution pages painted every
 * "completed" green, so an infeasible run looked like a success.
 */
export function completedWithoutPlan(run: RunOutcome): boolean {
  if (run.status !== "completed") return false;
  const verdict = run.solver_status ?? null;
  if (verdict !== null && NO_PLAN_VERDICTS.has(verdict)) return true;
  return verdict === "time_limit" && run.objective_value == null;
}
