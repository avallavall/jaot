import { describe, expect, it } from "vitest";
import { checkDatasetAgainstDeclarations } from "../dataset-validation";
import type { DslInspectResult } from "@/lib/types";

const INSPECT: DslInspectResult = {
  ok: true,
  sets: [{ name: "I", has_inline_values: false }],
  params: [
    { name: "w", index_sets: ["I"], arity: 1, has_inline_values: false },
    { name: "cap", index_sets: [], arity: 0, has_inline_values: false },
    { name: "c2", index_sets: ["I", "I"], arity: 2, has_inline_values: true },
  ],
};

const check = (data: unknown) =>
  checkDatasetAgainstDeclarations(JSON.stringify(data), INSPECT);

describe("checkDatasetAgainstDeclarations (S5)", () => {
  it("reports ok when every declaration-only symbol is filled with the right shape", () => {
    expect(
      check({ sets: { I: ["a"] }, params: { w: { a: 1 }, cap: 5 } }),
    ).toEqual([{ level: "ok", key: "datasetCheckOk" }]);
  });

  it("names missing declaration-only symbols (inline-valued ones are optional)", () => {
    const messages = check({ sets: {}, params: {} }) ?? [];
    expect(messages.map((m) => m.key).sort()).toEqual([
      "datasetCheckMissingParam",
      "datasetCheckMissingParam",
      "datasetCheckMissingSet",
    ]);
    // c2 has inline values -> NOT required.
    expect(messages.find((m) => m.values?.name === "c2")).toBeUndefined();
  });

  it("flags unknown sets/params (typo safety, mirrors the compiler)", () => {
    const messages =
      check({ sets: { I: ["a"], J: [] }, params: { w: { a: 1 }, cap: 1, peso: { a: 1 } } }) ??
      [];
    expect(messages.map((m) => [m.key, m.values?.name])).toEqual(
      expect.arrayContaining([
        ["datasetCheckUnknownSet", "J"],
        ["datasetCheckUnknownParam", "peso"],
      ]),
    );
  });

  it("flags shape problems: scalar vs indexed and composite-key arity", () => {
    const messages =
      check({
        sets: { I: ["a"] },
        params: { w: 3, cap: { a: 1 }, c2: { "a": 9 } },
      }) ?? [];
    expect(messages.map((m) => [m.key, m.values?.name])).toEqual(
      expect.arrayContaining([
        ["datasetCheckIndexed", "w"],
        ["datasetCheckScalar", "cap"],
        ["datasetCheckArity", "c2"],
      ]),
    );
  });

  it("stays quiet on invalid JSON or a failed inspect", () => {
    expect(checkDatasetAgainstDeclarations("{ not json", INSPECT)).toBeNull();
    expect(
      checkDatasetAgainstDeclarations("{}", { ok: false, error: { message: "x" } }),
    ).toBeNull();
    expect(checkDatasetAgainstDeclarations("[1,2]", INSPECT)).toBeNull();
  });
});
