import { describe, expect, it } from "vitest";
import { buildDatasetSkeleton } from "../dataset-skeleton";

describe("buildDatasetSkeleton (S2a)", () => {
  it("pre-fills only the symbols that need data: sets [], scalar 0, indexed {}", () => {
    const text = buildDatasetSkeleton({
      ok: true,
      sets: [
        { name: "I", has_inline_values: false },
        { name: "J", has_inline_values: true },
      ],
      params: [
        { name: "w", index_sets: ["I"], arity: 1, has_inline_values: false },
        { name: "cap", index_sets: [], arity: 0, has_inline_values: false },
        { name: "d", index_sets: ["J"], arity: 1, has_inline_values: true },
      ],
    });
    expect(text).not.toBeNull();
    expect(JSON.parse(text!)).toEqual({ sets: { I: [] }, params: { w: {}, cap: 0 } });
  });

  it("falls back to every symbol when nothing needs data (override template)", () => {
    const text = buildDatasetSkeleton({
      ok: true,
      sets: [{ name: "I", has_inline_values: true }],
      params: [{ name: "w", index_sets: ["I"], arity: 1, has_inline_values: true }],
    });
    expect(JSON.parse(text!)).toEqual({ sets: { I: [] }, params: { w: {} } });
  });

  it("returns null on inspect failure or a model with no data-facing symbols", () => {
    expect(buildDatasetSkeleton({ ok: false, error: { message: "boom" } })).toBeNull();
    expect(buildDatasetSkeleton({ ok: true, sets: [], params: [] })).toBeNull();
  });
});
