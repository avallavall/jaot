/**
 * Utilities for reading OptimizationResult data from ModelExecution.result_data.
 *
 * Handles both the current format (with `variables[]`) and the legacy format
 * where only `model: Record<string, number>` was stored.
 */

interface VariableEntry {
  name: string;
  type: string;
  value: number | string;
}

export interface ProgressPoint {
  iteration: number;
  objective: number;
  gap: number;
  timestamp: number;
}

export type ObjectiveSense = "minimize" | "maximize";

/**
 * Extract variable assignments from result_data.
 *
 * Current format: `result_data.variables` is `VariableSolution[]`.
 * Legacy format:  `result_data.model` is `{ varName: value }` — type is unavailable.
 */
export function extractVariables(
  resultData: Record<string, unknown> | undefined | null,
): VariableEntry[] {
  if (!resultData) return [];

  const vars = resultData.variables;
  if (Array.isArray(vars) && vars.length > 0) {
    return vars as VariableEntry[];
  }

  // Legacy: result_data.model is { varName: value }
  const model = resultData.model;
  if (model && typeof model === "object" && !Array.isArray(model)) {
    return Object.entries(model as Record<string, number>).map(([name, value]) => ({
      name,
      type: "unknown",
      value,
    }));
  }

  return [];
}

/**
 * Extract the convergence history captured by the SCIP event handler.
 * Returns an empty array when the field is missing or malformed.
 */
export function extractProgressHistory(
  resultData: Record<string, unknown> | undefined | null,
): ProgressPoint[] {
  if (!resultData) return [];
  const raw = resultData.progress_history;
  if (!Array.isArray(raw)) return [];

  return raw
    .map((entry, i) => {
      const p = entry as Record<string, unknown>;
      const objective = Number(p.objective);
      return {
        iteration: typeof p.iteration === "number" ? p.iteration : i + 1,
        objective,
        gap: typeof p.gap === "number" ? p.gap : Number(p.gap ?? 0),
        timestamp:
          typeof p.elapsed_seconds === "number"
            ? p.elapsed_seconds * 1000
            : typeof p.timestamp === "number"
              ? p.timestamp
              : i,
      };
    })
    .filter((p) => Number.isFinite(p.objective));
}

/**
 * Extract the objective sense from `input_data.objective.sense`. Defaults to
 * minimize when missing or unrecognised.
 */
export function extractObjectiveSense(
  inputData: Record<string, unknown> | undefined | null,
): ObjectiveSense {
  const sense = (inputData?.objective as { sense?: unknown } | undefined)?.sense;
  return sense === "maximize" ? "maximize" : "minimize";
}
