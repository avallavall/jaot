/**
 * # CONTRACT-TEST: the engine's own JSON message never reaches a reader.
 *
 * One of V8's shapes quotes the broken text back at whoever typed it, in
 * English, whatever language the page is in:
 *
 *   El JSON no es válido: Unexpected token 'a', "{"sets": [a,b,c }" is not valid JSON
 *
 * These cases are parsed from the real engine rather than written by hand, so
 * the day V8 changes its wording this file fails instead of the toast quietly
 * going back to saying nothing useful.
 */
import { describe, it, expect } from "vitest";

import { describeJsonError } from "../json-error";

function parseError(text: string): unknown {
  try {
    JSON.parse(text);
  } catch (err) {
    return err;
  }
  throw new Error(`"${text}" parsed — it was supposed to fail`);
}

describe("describeJsonError", () => {
  it("finds the line and column when the engine gives one", () => {
    const e = describeJsonError(parseError('{"a": 1,}'));
    expect(e.kind).toBe("positioned");
    expect(e.line).toBe(1);
    expect(e.column).toBe(9);
  });

  it("reads the position across several lines", () => {
    const e = describeJsonError(parseError('{\n  "a": 1,\n}'));
    expect(e.kind).toBe("positioned");
    expect(e.line).toBe(3);
    expect(e.column).toBeGreaterThan(0);
  });

  it("calls text that stops early truncated, not just invalid", () => {
    // A bracket left open is the usual cause and there is no position to give.
    const e = describeJsonError(parseError("[1,2,"));
    expect(e.kind).toBe("truncated");
    expect(e.line).toBeNull();
  });

  it("falls back to unknown on the shape that quotes the text back", () => {
    const e = describeJsonError(parseError('{"sets": [a,b,c }'));
    expect(e.kind).toBe("unknown");
    expect(e.line).toBeNull();
  });

  it("never returns any part of the engine's message", () => {
    /**
     * The whole point: whatever comes back must be safe to drop into a
     * translated sentence, so it holds numbers and a kind and nothing else.
     */
    for (const bad of ['{"sets": [a,b,c }', "[1,2,", '{"a" 1}', "{", '{"a": 1} extra']) {
      const e = describeJsonError(parseError(bad));
      const values = Object.values(e);
      expect(values.every((v) => v === null || typeof v === "number" || typeof v === "string")).toBe(
        true,
      );
      expect(JSON.stringify(e)).not.toContain("Unexpected");
      expect(JSON.stringify(e)).not.toContain("JSON at position");
    }
  });

  it("survives something that is not an Error at all", () => {
    expect(describeJsonError("plain string").kind).toBe("unknown");
    expect(describeJsonError(null).kind).toBe("unknown");
  });
});
