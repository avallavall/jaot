import type { DslInspectResult } from "@/lib/types";

/**
 * Build the JSON skeleton a dataset editor pre-fills from the model's REAL
 * declarations (S2a): sets → `[]`, scalar params → `0`, indexed params → `{}`.
 *
 * A dataset replaces symbols WHOLE, so the skeleton lists only the symbols that
 * NEED data (declared without inline values) — pre-filling an inline-valued set
 * with `[]` would silently empty it on save. When nothing needs data, it falls
 * back to every declared symbol as an explicit override template.
 */
export function buildDatasetSkeleton(inspect: DslInspectResult): string | null {
  if (!inspect.ok) return null;
  const allSets = inspect.sets ?? [];
  const allParams = inspect.params ?? [];
  let sets = allSets.filter((s) => !s.has_inline_values);
  let params = allParams.filter((p) => !p.has_inline_values);
  if (sets.length === 0 && params.length === 0) {
    sets = allSets;
    params = allParams;
  }
  if (sets.length === 0 && params.length === 0) return null;

  const skeleton = {
    sets: Object.fromEntries(sets.map((s) => [s.name, []])),
    params: Object.fromEntries(params.map((p) => [p.name, p.arity === 0 ? 0 : {}])),
  };
  return JSON.stringify(skeleton, null, 2);
}
