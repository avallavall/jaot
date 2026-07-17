import type { DslInspectResult } from "@/lib/types";

/**
 * One guidance message from the live dataset↔model check (S5). `level: "ok"` is
 * the single "fills the model" line; `"warn"` entries name what's off.
 */
export interface DatasetCheckMessage {
  level: "ok" | "warn";
  /** i18n key under `studio.` */
  key:
    | "datasetCheckOk"
    | "datasetCheckMissingSet"
    | "datasetCheckMissingParam"
    | "datasetCheckUnknownSet"
    | "datasetCheckUnknownParam"
    | "datasetCheckArity"
    | "datasetCheckScalar"
    | "datasetCheckIndexed";
  /** Interpolation values for the message. */
  values?: Record<string, string | number>;
}

/**
 * Pure client-side check of a dataset's JSON against the model's declarations
 * (from parse-only `/dsl/inspect`). GUIDANCE ONLY — the server compile stays the
 * source of truth; this mirrors its main rules so the editor can say "missing
 * `w` / unknown `peso` / arity mismatch" while typing, without a round-trip.
 *
 * Returns `null` when the text is not (yet) valid JSON — the editor stays quiet
 * mid-keystroke rather than nagging about syntax.
 */
export function checkDatasetAgainstDeclarations(
  text: string,
  inspect: DslInspectResult,
): DatasetCheckMessage[] | null {
  if (!inspect.ok) return null;
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const dataSets = asRecord((data as Record<string, unknown>).sets);
  const dataParams = asRecord((data as Record<string, unknown>).params);

  const declaredSets = new Map((inspect.sets ?? []).map((s) => [s.name, s]));
  const declaredParams = new Map((inspect.params ?? []).map((p) => [p.name, p]));
  const messages: DatasetCheckMessage[] = [];

  // Declaration-only symbols MUST be filled by the dataset (inline ones are optional
  // overrides — replacement is whole-symbol, so absence just keeps the inline values).
  for (const [name, s] of declaredSets) {
    if (!s.has_inline_values && !(name in dataSets)) {
      messages.push({ level: "warn", key: "datasetCheckMissingSet", values: { name } });
    }
  }
  for (const [name, p] of declaredParams) {
    if (!p.has_inline_values && !(name in dataParams)) {
      messages.push({ level: "warn", key: "datasetCheckMissingParam", values: { name } });
    }
  }

  // Symbols the model does not declare are compile errors by design (typo safety).
  for (const name of Object.keys(dataSets)) {
    if (!declaredSets.has(name)) {
      messages.push({ level: "warn", key: "datasetCheckUnknownSet", values: { name } });
    }
  }
  for (const [name, value] of Object.entries(dataParams)) {
    const decl = declaredParams.get(name);
    if (!decl) {
      messages.push({ level: "warn", key: "datasetCheckUnknownParam", values: { name } });
      continue;
    }
    // Shape: scalar params take a number; indexed ones an object whose keys carry
    // exactly `arity` comma-joined parts.
    if (decl.arity === 0) {
      if (typeof value !== "number") {
        messages.push({ level: "warn", key: "datasetCheckScalar", values: { name } });
      }
      continue;
    }
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      messages.push({ level: "warn", key: "datasetCheckIndexed", values: { name } });
      continue;
    }
    for (const key of Object.keys(value)) {
      const parts = key.split(",").length;
      if (parts !== decl.arity) {
        messages.push({
          level: "warn",
          key: "datasetCheckArity",
          values: { name, key, expected: decl.arity, got: parts },
        });
        break; // one arity message per param is enough guidance
      }
    }
  }

  if (messages.length === 0) return [{ level: "ok", key: "datasetCheckOk" }];
  return messages;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
