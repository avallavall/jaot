import type { OptimizationProblem } from "@/lib/types";

export interface ModelStats {
  varTotal: number;
  varBinary: number;
  varInteger: number;
  varContinuous: number;
  constraintTotal: number;
  constraintsByOperator: Record<string, number>;
  nonzeros: number;
  /** nonzeros / (constraints * variables); 0 when either is empty. */
  density: number;
  /** LP | MILP | IP | BIP | "—" (quadratic classes land with the DSL slice). */
  problemClass: string;
}

const VAR_TOKEN = /[a-zA-Z_]\w*/g;

/** Count variable occurrences on a constraint's LHS — a cheap nonzero proxy. */
function countTerms(expression: string): number {
  const lhs = expression.split(/<=|>=|==|=/)[0] ?? "";
  const matches = lhs.match(VAR_TOKEN);
  return matches ? matches.length : 0;
}

function operatorOf(expression: string): string {
  if (expression.includes("<=")) return "<=";
  if (expression.includes(">=")) return ">=";
  if (expression.includes("==")) return "==";
  return "=";
}

/**
 * Cheap, pure, client-side model statistics derived from the canonical
 * `OptimizationProblem` in a single pass — drives the live-stats rail and the
 * Analyze tab. The authoritative backend `ModelStatsService` (presolve, sparsity,
 * health score) lands in P1.
 */
export function selectModelStats(problem: OptimizationProblem): ModelStats {
  let varBinary = 0;
  let varInteger = 0;
  let varContinuous = 0;
  for (const v of problem.variables) {
    if (v.type === "binary") varBinary++;
    else if (v.type === "integer") varInteger++;
    else varContinuous++;
  }
  const varTotal = problem.variables.length;
  const constraintTotal = problem.constraints.length;

  const constraintsByOperator: Record<string, number> = {};
  let nonzeros = 0;
  for (const c of problem.constraints) {
    const op = operatorOf(c.expression);
    constraintsByOperator[op] = (constraintsByOperator[op] ?? 0) + 1;
    nonzeros += countTerms(c.expression);
  }

  const denom = constraintTotal * varTotal;
  const density = denom > 0 ? nonzeros / denom : 0;

  let problemClass = "—";
  if (varTotal > 0) {
    const hasInt = varInteger > 0 || varBinary > 0;
    if (!hasInt) problemClass = "LP";
    else if (varContinuous === 0) problemClass = varInteger === 0 ? "BIP" : "IP";
    else problemClass = "MILP";
  }

  return {
    varTotal,
    varBinary,
    varInteger,
    varContinuous,
    constraintTotal,
    constraintsByOperator,
    nonzeros,
    density,
    problemClass,
  };
}
