// Pure helpers for the studio versioning UI — kept React-free so they unit-test
// without a component graph.

import type { CanvasDiff, NodeChange, EdgeChange } from "@/lib/builder/diff";

/** A commit requires a non-empty "What changed?" summary. */
export function isValidSummary(summary: string): boolean {
  return summary.trim().length > 0;
}

/** The deterministic suggested commit message, from the canvas diff (P4 adds an AI one). */
export function suggestedSummary(diff: CanvasDiff | null): string {
  if (!diff || diff.isEmpty) return "";
  return diff.summary;
}

export type DiffCategory = "variable" | "constraint" | "objective" | "link";

export interface DetectedChange {
  category: DiffCategory;
  added: number;
  removed: number;
  modified: number;
}

function counts(changes: Array<NodeChange | EdgeChange>): Omit<DetectedChange, "category"> {
  return changes.reduce(
    (acc, c) => {
      acc[c.type] += 1;
      return acc;
    },
    { added: 0, removed: 0, modified: 0 }
  );
}

/** A compact, structured "+2 / −1 / ~1 per category" summary of a diff. */
export function detectedChanges(diff: CanvasDiff | null): DetectedChange[] {
  if (!diff || diff.isEmpty) return [];
  const rows: DetectedChange[] = [
    { category: "variable", ...counts(diff.variables) },
    { category: "constraint", ...counts(diff.constraints) },
    { category: "objective", ...counts(diff.objective) },
    { category: "link", ...counts(diff.edges) },
  ];
  return rows.filter((r) => r.added > 0 || r.removed > 0 || r.modified > 0);
}

export interface UncommittedState {
  /** Whether to show the "uncommitted changes" ambient line. */
  show: boolean;
  /** The sequence the edits are relative to (latest committed version), or null if none yet. */
  sinceSequence: number | null;
}

/** The ambient "N uncommitted changes since vK" state, derived from the draft-dirty flag. */
export function uncommittedSince(
  headDirty: boolean,
  latestSequence: number | null
): UncommittedState {
  return { show: headDirty, sinceSequence: headDirty ? latestSequence : null };
}
