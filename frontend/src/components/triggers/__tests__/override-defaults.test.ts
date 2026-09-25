import { describe, it, expect } from "vitest";
import { defaultToText, parseDefault } from "../override-defaults";

describe("parseDefault", () => {
  it("stores a number field's default as a number", () => {
    expect(parseDefault("number", " 4.5 ")).toEqual({ ok: true, value: 4.5 });
    expect(parseDefault("integer", "7")).toEqual({ ok: true, value: 7 });
    expect(parseDefault("integer", "7.5")).toEqual({ ok: false });
    expect(parseDefault("number", "four")).toEqual({ ok: false });
  });

  it("reads booleans, arrays and objects by their type", () => {
    expect(parseDefault("boolean", "false")).toEqual({ ok: true, value: false });
    expect(parseDefault("boolean", "yes")).toEqual({ ok: false });
    expect(parseDefault("array", "[1, 2]")).toEqual({ ok: true, value: [1, 2] });
    expect(parseDefault("array", '{"a": 1}')).toEqual({ ok: false });
    expect(parseDefault("object", '{"a": 1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(parseDefault("object", "[1]")).toEqual({ ok: false });
  });

  it("reads an empty box as no default", () => {
    expect(parseDefault("string", "  ")).toEqual({ ok: true, value: null });
    expect(parseDefault("number", "")).toEqual({ ok: true, value: null });
  });

  it("round-trips what defaultToText shows", () => {
    for (const [type, value] of [
      ["string", "jaos"],
      ["number", 3],
      ["boolean", true],
      ["array", [1, 2]],
    ] as const) {
      expect(parseDefault(type, defaultToText(value))).toEqual({ ok: true, value });
    }
    expect(defaultToText(null)).toBe("");
  });
});
