import { describe, it, expect } from "vitest";
import { buildSolutionGroups, flattenSolutionRows } from "@/lib/solution-grouping";
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

describe("flattenSolutionRows", () => {
  const many = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      v(`assign_v1_o${i}`, 1, { family: "assign", index_tuple: ["v1", `o${i}`] }),
    );

  it("puts a family header before its entry rows", () => {
    const rows = flattenSolutionRows(buildSolutionGroups(many(3)));
    expect(rows.map((r) => r.kind)).toEqual(["family", "entries"]);
    expect(rows[0]).toMatchObject({ kind: "family", family: "assign", count: 3 });
  });

  // A single family can hold every variable in the model; one row per group
  // would make that row as heavy as the unbounded render we are replacing.
  it("splits an oversized group into bounded rows, flagging the continuations", () => {
    const rows = flattenSolutionRows(buildSolutionGroups(many(130)), 60);
    const entryRows = rows.filter((r) => r.kind === "entries");
    expect(entryRows.map((r) => r.entries.length)).toEqual([60, 60, 10]);
    expect(entryRows.map((r) => r.continued)).toEqual([false, true, true]);
    // …and no chip is lost or duplicated across the split.
    const labels = entryRows.flatMap((r) => r.entries.map((e) => e.label));
    expect(labels).toHaveLength(130);
    expect(new Set(labels).size).toBe(130);
  });

  it("keeps families in first-seen order and appends the ungrouped tail", () => {
    const rows = flattenSolutionRows(
      buildSolutionGroups([
        v("route_a_b", 1, { family: "route", index_tuple: ["a", "b"] }),
        v("flow_x", 4.2, { family: "flow", index_tuple: ["x"] }),
        v("total_cost", 99, { type: "continuous" }),
      ]),
    );
    expect(rows.map((r) => r.kind)).toEqual([
      "family",
      "entries",
      "family",
      "entries",
      "ungrouped-header",
      "ungrouped",
    ]);
    expect(rows.filter((r) => r.kind === "family").map((r) => r.family)).toEqual([
      "route",
      "flow",
    ]);
  });

  it("emits no ungrouped header when everything carried structure", () => {
    const rows = flattenSolutionRows(buildSolutionGroups(many(2)));
    expect(rows.some((r) => r.kind === "ungrouped-header")).toBe(false);
  });
});
