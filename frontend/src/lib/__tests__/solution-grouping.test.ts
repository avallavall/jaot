import { describe, it, expect } from "vitest";
import { buildSolutionGroups } from "@/lib/solution-grouping";
import type { VariableSolution } from "@/lib/types";

function v(
  name: string,
  value: number,
  extra: Partial<VariableSolution> = {},
): VariableSolution {
  return { name, value, type: "binary", ...extra } as VariableSolution;
}

describe("buildSolutionGroups", () => {
  it("groups a multi-index family by its first index", () => {
    const { groups, hasStructure } = buildSolutionGroups([
      v("assign_v3_o107", 1, { family: "assign", index_tuple: ["v3", "o107"] }),
      v("assign_v3_o12", 1, { family: "assign", index_tuple: ["v3", "o12"] }),
      v("assign_v1_o44", 1, { family: "assign", index_tuple: ["v1", "o44"] }),
    ]);
    expect(hasStructure).toBe(true);
    const byKey = Object.fromEntries(groups.map((g) => [g.key, g.entries.map((e) => e.label)]));
    expect(byKey["v3"]).toEqual(["o107", "o12"]);
    expect(byKey["v1"]).toEqual(["o44"]);
  });

  it("puts a single-index family in one null-key bucket", () => {
    const { groups } = buildSolutionGroups([
      v("take_a", 1, { family: "take", index_tuple: ["a"] }),
      v("take_c", 1, { family: "take", index_tuple: ["c"] }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBeNull();
    expect(groups[0].entries.map((e) => e.label)).toEqual(["a", "c"]);
  });

  it("routes variables with no family to the ungrouped bucket", () => {
    const { groups, ungrouped, hasStructure } = buildSolutionGroups([
      v("x", 3.5, { type: "continuous" }),
      v("y", 2, { type: "integer" }),
    ]);
    expect(hasStructure).toBe(false);
    expect(groups).toHaveLength(0);
    expect(ungrouped.map((e) => e.name)).toEqual(["x", "y"]);
  });

  it("keeps distinct families separate and preserves first-seen order", () => {
    const { groups } = buildSolutionGroups([
      v("route_1_2", 1, { family: "route", index_tuple: ["1", "2"] }),
      v("flow_1_2", 4.2, { type: "continuous", family: "flow", index_tuple: ["1", "2"] }),
    ]);
    expect(groups.map((g) => g.family)).toEqual(["route", "flow"]);
    expect(groups[1].entries[0].value).toBe(4.2);
  });
});
