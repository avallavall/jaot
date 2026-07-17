/**
 * Group a solved variable vector by its recovered index structure (A1).
 *
 * A binary assignment/routing solution is a wall of `assign_v3_o107 = 1`. The
 * backend now tags each variable with `family` + `index_tuple`, so we can
 * present it as the structure the model actually has: family → first index →
 * the remaining members. Variables with no recovered family (continuous, custom
 * naming, legacy rows) fall through to an ungrouped bucket and render flat.
 */
import type { VariableSolution } from "@/lib/types";

export interface SolutionLeaf {
  /** What shows inside a group: the remaining index tuple ("o107") for a
   *  multi-index family, or the sole index for a single-index one. */
  label: string;
  value: number;
  name: string;
  type: string;
}

export interface SolutionGroup {
  family: string;
  /** The first index a multi-index family is grouped by ("v3"); null for a
   *  single-index family (no sub-grouping — one bucket holds the whole family). */
  key: string | null;
  entries: SolutionLeaf[];
}

export interface GroupedSolution {
  groups: SolutionGroup[];
  /** Variables with no recovered family — rendered flat as a fallback. */
  ungrouped: SolutionLeaf[];
  /** True when at least one variable carried a family (structure to show). */
  hasStructure: boolean;
}

export function buildSolutionGroups(variables: VariableSolution[]): GroupedSolution {
  const ungrouped: SolutionLeaf[] = [];
  // family -> firstIndexKey -> leaves. "" key = the single-index family bucket.
  const byFamily = new Map<string, Map<string, SolutionLeaf[]>>();
  let hasStructure = false;

  for (const v of variables) {
    const family = v.family;
    const idx = v.index_tuple;
    if (!family || !idx || idx.length === 0) {
      ungrouped.push({ label: v.name, value: Number(v.value), name: v.name, type: v.type });
      continue;
    }
    hasStructure = true;
    const multi = idx.length >= 2;
    const key = multi ? idx[0] : "";
    const label = multi ? idx.slice(1).join(", ") : idx[0];
    let keyMap = byFamily.get(family);
    if (!keyMap) {
      keyMap = new Map();
      byFamily.set(family, keyMap);
    }
    const leaves = keyMap.get(key);
    if (leaves) {
      leaves.push({ label, value: Number(v.value), name: v.name, type: v.type });
    } else {
      keyMap.set(key, [{ label, value: Number(v.value), name: v.name, type: v.type }]);
    }
  }

  const groups: SolutionGroup[] = [];
  for (const [family, keyMap] of byFamily) {
    for (const [key, entries] of keyMap) {
      groups.push({ family, key: key === "" ? null : key, entries });
    }
  }
  return { groups, ungrouped, hasStructure };
}
