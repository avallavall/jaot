import { describe, it, expect } from "vitest";
import type { CanvasDiff } from "@/lib/builder/diff";
import {
  isValidSummary,
  suggestedSummary,
  detectedChanges,
  uncommittedSince,
} from "../commit-helpers";

const emptyDiff: CanvasDiff = {
  variables: [],
  constraints: [],
  objective: [],
  edges: [],
  summary: "",
  isEmpty: true,
};

function diffWith(partial: Partial<CanvasDiff>): CanvasDiff {
  return {
    variables: [],
    constraints: [],
    objective: [],
    edges: [],
    summary: "changes",
    isEmpty: false,
    ...partial,
  };
}

describe("commit-helpers", () => {
  it("isValidSummary rejects empty / whitespace, accepts real text", () => {
    expect(isValidSummary("")).toBe(false);
    expect(isValidSummary("   ")).toBe(false);
    expect(isValidSummary("\t\n ")).toBe(false);
    expect(isValidSummary("Cap overtime at 8h")).toBe(true);
    expect(isValidSummary("  x  ")).toBe(true);
  });

  it("suggestedSummary returns the diff summary, empty for null/empty diff", () => {
    expect(suggestedSummary(null)).toBe("");
    expect(suggestedSummary(emptyDiff)).toBe("");
    expect(suggestedSummary(diffWith({ summary: "Added 2 constraints" }))).toBe(
      "Added 2 constraints"
    );
  });

  it("detectedChanges aggregates per category and drops empty categories", () => {
    const diff = diffWith({
      variables: [
        { type: "added", nodeId: "v1", nodeName: "x", nodeType: "variable" },
        { type: "added", nodeId: "v2", nodeName: "y", nodeType: "variable" },
        { type: "modified", nodeId: "v3", nodeName: "z", nodeType: "variable" },
      ],
      constraints: [
        { type: "removed", nodeId: "c1", nodeName: "c", nodeType: "constraint" },
      ],
      edges: [{ type: "added", edgeId: "e1", sourceNode: "x", targetNode: "c" }],
    });

    expect(detectedChanges(diff)).toEqual([
      { category: "variable", added: 2, removed: 0, modified: 1 },
      { category: "constraint", added: 0, removed: 1, modified: 0 },
      { category: "link", added: 1, removed: 0, modified: 0 },
    ]);
    expect(detectedChanges(null)).toEqual([]);
    expect(detectedChanges(emptyDiff)).toEqual([]);
  });

  it("uncommittedSince reflects the dirty flag + latest sequence", () => {
    expect(uncommittedSince(false, 5)).toEqual({ show: false, sinceSequence: null });
    expect(uncommittedSince(true, 5)).toEqual({ show: true, sinceSequence: 5 });
    expect(uncommittedSince(true, null)).toEqual({ show: true, sinceSequence: null });
  });
});
