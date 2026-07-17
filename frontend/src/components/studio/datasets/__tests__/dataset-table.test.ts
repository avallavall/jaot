import { describe, expect, it } from "vitest";
import { tableFromJson, tableToJson } from "../dataset-table";

const SAMPLE = JSON.stringify({
  sets: { I: ["a", "b", "c"] },
  params: { cap: 10, w: { a: 2, b: 3 }, cost: { "a,p": 1, "b,q": 4 } },
});

describe("dataset table transforms (S2b)", () => {
  it("round-trips sets, scalar and indexed params through the table model", () => {
    const model = tableFromJson(SAMPLE);
    expect(model).not.toBeNull();
    expect(model!.sets).toEqual([{ name: "I", membersText: "a, b, c" }]);
    expect(model!.params).toEqual([
      { name: "cap", kind: "scalar", value: "10" },
      {
        name: "w",
        kind: "indexed",
        arity: 1,
        rows: [
          { parts: ["a"], value: "2" },
          { parts: ["b"], value: "3" },
        ],
      },
      {
        name: "cost",
        kind: "indexed",
        arity: 2,
        rows: [
          { parts: ["a", "p"], value: "1" },
          { parts: ["b", "q"], value: "4" },
        ],
      },
    ]);
    expect(JSON.parse(tableToJson(model!))).toEqual(JSON.parse(SAMPLE));
  });

  it("omits incomplete rows and empty scalars instead of serializing broken data", () => {
    const model = tableFromJson(SAMPLE)!;
    model.params[0] = { name: "cap", kind: "scalar", value: "" };
    (model.params[1].kind === "indexed" ? model.params[1].rows : []).push({
      parts: [""],
      value: "9",
    });
    const out = JSON.parse(tableToJson(model));
    expect(out.params.cap).toBeUndefined();
    expect(out.params.w).toEqual({ a: 2, b: 3 });
  });

  it("parses member edits back into clean lists", () => {
    const model = tableFromJson(SAMPLE)!;
    model.sets[0].membersText = " a ,  d,, e ";
    expect(JSON.parse(tableToJson(model)).sets.I).toEqual(["a", "d", "e"]);
  });

  it("returns null for text the table cannot faithfully represent", () => {
    expect(tableFromJson("{ not json")).toBeNull();
    expect(tableFromJson('{"sets": {"I": "abc"}}')).toBeNull();
    expect(tableFromJson('{"params": {"w": {"a": "x"}}}')).toBeNull();
    expect(tableFromJson('{"params": {"w": {"a": 1, "b,c": 2}}}')).toBeNull(); // ragged
    expect(tableFromJson('{"params": {"w": [1, 2]}}')).toBeNull();
  });
});
