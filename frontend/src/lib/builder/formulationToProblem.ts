import type { Formulation } from "@/lib/llm-types";
import type { OptimizationProblem } from "@/lib/types";

/** Build a solver-ready OptimizationProblem from an AI formulation. */
export function formulationToProblem(formulation: Formulation): OptimizationProblem {
  return {
    name: formulation.problem_name || "ai_formulation",
    description: formulation.summary || "",
    variables: formulation.variables.map((v) => ({
      name: v.name,
      type: v.type,
      lower_bound: v.lower_bound,
      upper_bound: v.upper_bound,
    })),
    constraints: formulation.constraints.map((c) => ({
      name: c.name,
      expression: c.expression,
    })),
    objective: {
      sense: formulation.objective.sense,
      expression: formulation.objective.expression,
    },
  };
}
