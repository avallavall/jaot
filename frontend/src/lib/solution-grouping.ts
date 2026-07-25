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

/** One rendered line of the grouped view — the unit the virtualizer windows over. */
export type SolutionRow =
  | { kind: "family"; family: string; count: number }
  | {
      kind: "entries";
      family: string;
      /** First index this line belongs to (null for a single-index family). */
      key: string | null;
      entries: SolutionLeaf[];
      /** True when this line continues a group split across several lines. */
      continued: boolean;
    }
  | { kind: "ungrouped-header" }
  | { kind: "ungrouped"; entries: SolutionLeaf[] };

/** Chips per line. Bounds each row's height so a windowed list can estimate it,
 *  and keeps one 20k-member family from becoming a single monstrous row. */
export const ROW_CHUNK = 60;

/**
 * Flatten a grouped solution into bounded-height rows, families in first-seen
 * order with a header carrying the family's full count.
 *
 * This is what makes windowing possible: rendering one row per group would put
 * a 20k-entry family in a single DOM node (nothing gained), while one row per
 * chip would lose the family → index structure the view exists to show.
 */
export function flattenSolutionRows(
  grouped: GroupedSolution,
  chunkSize: number = ROW_CHUNK,
): SolutionRow[] {
  const byFamily = new Map<string, SolutionGroup[]>();
  for (const g of grouped.groups) {
    const list = byFamily.get(g.family);
    if (list) list.push(g);
    else byFamily.set(g.family, [g]);
  }

  const rows: SolutionRow[] = [];
  for (const [family, groups] of byFamily) {
    rows.push({
      kind: "family",
      family,
      count: groups.reduce((n, g) => n + g.entries.length, 0),
    });
    for (const group of groups) {
      for (let i = 0; i < group.entries.length; i += chunkSize) {
        rows.push({
          kind: "entries",
          family,
          key: group.key,
          entries: group.entries.slice(i, i + chunkSize),
          continued: i > 0,
        });
      }
    }
  }

  if (grouped.ungrouped.length > 0) {
    rows.push({ kind: "ungrouped-header" });
    for (let i = 0; i < grouped.ungrouped.length; i += chunkSize) {
      rows.push({ kind: "ungrouped", entries: grouped.ungrouped.slice(i, i + chunkSize) });
    }
  }
  return rows;
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
