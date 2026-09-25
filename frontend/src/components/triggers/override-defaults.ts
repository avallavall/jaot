import type { OverrideField } from "@/lib/types";

/** The text an input shows for a stored default. Empty means no default. */
export function defaultToText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export type ParsedDefault = { ok: true; value: unknown } | { ok: false };

/**
 * Read a default typed into the edit form as the field's declared type.
 *
 * Empty text means "no default" and is stored as null, which the server reads
 * the same way. A number field gets a number, not the string "5": the default
 * is written into the model as it is stored.
 */
export function parseDefault(type: OverrideField["type"], text: string): ParsedDefault {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: true, value: null };
  switch (type) {
    case "string":
      return { ok: true, value: trimmed };
    case "number": {
      const n = Number(trimmed);
      return Number.isFinite(n) ? { ok: true, value: n } : { ok: false };
    }
    case "integer": {
      const n = Number(trimmed);
      return Number.isInteger(n) ? { ok: true, value: n } : { ok: false };
    }
    case "boolean":
      if (trimmed === "true") return { ok: true, value: true };
      if (trimmed === "false") return { ok: true, value: false };
      return { ok: false };
    case "array":
    case "object": {
      try {
        const value: unknown = JSON.parse(trimmed);
        const isArray = Array.isArray(value);
        const isObject = typeof value === "object" && value !== null && !isArray;
        return (type === "array" ? isArray : isObject) ? { ok: true, value } : { ok: false };
      } catch {
        return { ok: false };
      }
    }
    default:
      return { ok: false };
  }
}
