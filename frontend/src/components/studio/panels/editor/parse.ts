import type { OptimizationProblem } from "@/lib/types";

/** The structural field whose absence makes parsed JSON not a model. */
export type ShapeField = "object" | "variables" | "constraints" | "objective";

/**
 * Outcome of parsing the Editor's text. `syntax` carries the raw parser message
 * (a technical detail shown verbatim); `shape` carries a translatable field code.
 */
export type ParseResult =
  | { ok: true; problem: OptimizationProblem }
  | { ok: false; kind: "syntax"; detail: string }
  | { ok: false; kind: "shape"; field: ShapeField };

/**
 * Parse the Editor textarea into a canonical `OptimizationProblem`, defensively.
 * Pure + unit-tested: a syntax error or a JSON that is not a model shape returns a
 * typed failure instead of throwing, so a typo is never applied to the canonical
 * model (the canvas/Solve keep the last-good model — R6). Deep/semantic validation
 * is the backend's job (`api.validateProblem`); this is the cheap structural gate.
 */
export function parseModelText(text: string): ParseResult {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err: unknown) {
    return { ok: false, kind: "syntax", detail: getMessage(err) };
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return { ok: false, kind: "shape", field: "object" };
  }
  const obj = data as Record<string, unknown>;
  if (!Array.isArray(obj.variables)) return { ok: false, kind: "shape", field: "variables" };
  if (!Array.isArray(obj.constraints)) return { ok: false, kind: "shape", field: "constraints" };
  if (typeof obj.objective !== "object" || obj.objective === null) {
    return { ok: false, kind: "shape", field: "objective" };
  }
  return { ok: true, problem: data as OptimizationProblem };
}

function getMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
