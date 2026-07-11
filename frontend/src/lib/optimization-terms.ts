/**
 * Glossary of optimization domain terms used throughout the application.
 * Term names and formulas are universal (not translated).
 * Definitions and examples are in translation JSON (glossary namespace).
 */

export interface TermDefinition {
  term: string;
  formula?: string;
}

export const OPTIMIZATION_TERMS: Record<string, TermDefinition> = {
  "shadow-price": {
    term: "Shadow Price",
  },
  "binding-constraint": {
    term: "Binding Constraint",
  },
  "slack-value": {
    term: "Slack Value",
  },
  "pareto-front": {
    term: "Pareto Front",
  },
  "warm-start": {
    term: "Warm Start",
  },
  "lp-relaxation": {
    term: "LP Relaxation",
    formula: "min cᵀx  s.t. Ax ≤ b, x ∈ ℝⁿ (integrality dropped)",
  },
  "objective-value": {
    term: "Objective Value",
  },
  "formulation": {
    term: "Formulation",
  },
  "decision-variable": {
    term: "Decision Variable",
  },
  "constraint": {
    term: "Constraint",
  },
  "objective": {
    term: "Objective",
  },
  "feasibility": {
    term: "Feasibility",
  },
  "infeasible": {
    term: "Infeasible",
  },
  "optimal": {
    term: "Optimal",
  },
  "relaxation": {
    term: "Relaxation",
  },
};

/**
 * Look up a term definition by key.
 * Returns undefined if the key is not found.
 */
export function getTermDefinition(
  key: string
): TermDefinition | undefined {
  return OPTIMIZATION_TERMS[key];
}
