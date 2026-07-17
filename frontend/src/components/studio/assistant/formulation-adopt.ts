import type { Formulation } from "@/lib/llm-types";

/**
 * Whether a formulation is a real model worth adopting into the canonical store.
 * A refusal (`problem_name === "not_applicable"`) or a variable-less answer is the
 * assistant declining / asking a question — folding it in would wipe the user's work.
 */
export function isRealFormulation(formulation: Formulation): boolean {
  return (
    formulation.problem_name !== "not_applicable" &&
    (formulation.variables?.length ?? 0) > 0
  );
}

/** Turn a snake_case `problem_name` into a Title-Cased display name. */
export function humanizeProblemName(problemName: string): string {
  return problemName.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
