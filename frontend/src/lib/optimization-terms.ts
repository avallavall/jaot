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
  },
  "objective-value": {
    term: "Objective Value",
  },
  "base-cost": {
    term: "Base Cost",
    formula: "1 credit (fixed)",
  },
  "variable-cost": {
    term: "Variable Cost",
    formula: "num_variables \u00d7 0.1",
  },
  "integer-penalty": {
    term: "Integer Penalty",
    formula: "int_vars \u00d7 0.3 + bin_vars \u00d7 0.2",
  },
  "constraint-cost": {
    term: "Constraint Cost",
    formula: "num_constraints \u00d7 0.05",
  },
  "time-bonus": {
    term: "Time Bonus",
    formula: "max(0, (time_limit - 30) \u00d7 0.1)",
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
