/**
 * # CONTRACT-TEST: the engine's own JSON message never reaches a reader.
 *
 * One of V8's shapes quotes the broken text back at whoever typed it, in
 * English, whatever language the page is in:
 *
 *   El JSON no es válido: Unexpected token 'a', "{"sets": [a,b,c }" is not valid JSON
 *
 * **The first version of this file parsed the real engine and asserted on the
 * one wording it happened to produce.** That reads as thorough and is not: it
 * tests whichever engine runs the suite. Written on node 24, it went red on CI,
 * which runs node 20 — and node 20 is what the production image ships and what
 * the older half of the browsers out there are close to. The failure was real:
 * `describeJsonError` returned "unknown" for every parse error on any engine
 * but the author's.
 *
 * So the wordings below are written out rather than parsed. Each one is a real
 * message from a real engine, and the last block still asks the engine at hand
 * — whichever it is — so that the day V8 changes its mind again this file says
 * so instead of the toast quietly going back to saying nothing useful.
 */
import { describe, it, expect } from "vitest";

import { describeJsonError } from "../json-error";

/** Build the error the way each engine builds it. */
const asError = (message: string) => new SyntaxError(message);

describe("describeJsonError across the engines a reader may be on", () => {
  it("reads V8 from node 24, which gives a line and a column in brackets", () => {
    const e = describeJsonError(
      asError(
        "Expected double-quoted property name in JSON at position 8 (line 1 column 9)",
      ),
      '{"a": 1,}',
    );
    expect(e).toEqual({ kind: "positioned", line: 1, column: 9 });
  });

  it("reads V8 from node 20, which gives only a byte offset", () => {
    const e = describeJsonError(
      asError("Unexpected token } in JSON at position 8"),
      '{"a": 1,}',
    );
    expect(e).toEqual({ kind: "positioned", line: 1, column: 9 });
  });

  it("reads Firefox, which gives a line and a column without brackets", () => {
    const e = describeJsonError(
      asError(
        "JSON.parse: expected double-quoted property name at line 1 column 9 of the JSON data",
      ),
      '{"a": 1,}',
    );
    expect(e).toEqual({ kind: "positioned", line: 1, column: 9 });
  });

  it("counts the line and the column across several lines from an offset", () => {
    const source = '{\n  "a": 1,\n}';
    // Position 12 is the closing brace on the third line.
    const e = describeJsonError(asError("Unexpected token } in JSON at position 12"), source);
    expect(e.kind).toBe("positioned");
    expect(e.line).toBe(3);
    expect(e.column).toBe(1);
  });

  it("says unknown on an offset with no text to measure it against", () => {
    // A number pointing into thin air helps nobody, so it is not offered.
    const e = describeJsonError(asError("Unexpected token } in JSON at position 8"));
    expect(e.kind).toBe("unknown");
  });

  it("says unknown on Safari, which gives no position at all", () => {
    const e = describeJsonError(asError("JSON Parse error: Expected '\"'"), '{"a": 1,}');
    expect(e.kind).toBe("unknown");
  });

  it("calls text that stops early truncated, not just invalid", () => {
    // A bracket left open is the usual cause and there is no position to give.
    for (const message of [
      "Unexpected end of JSON input",
      "JSON.parse: end of data while reading object contents",
      "JSON Parse error: Unexpected EOF",
    ]) {
      const e = describeJsonError(asError(message), "[1,2,");
      expect(e.kind, message).toBe("truncated");
      expect(e.line, message).toBeNull();
    }
  });

  it("falls back to unknown on the shape that quotes the text back", () => {
    const e = describeJsonError(
      asError('Unexpected token \'a\', "{"sets": [a,b,c }" is not valid JSON'),
      '{"sets": [a,b,c }',
    );
    expect(e.kind).toBe("unknown");
    expect(e.line).toBeNull();
  });
});

describe("the engine actually running this suite", () => {
  function parseError(text: string): unknown {
    try {
      JSON.parse(text);
    } catch (err) {
      return err;
    }
    throw new Error(`"${text}" parsed — it was supposed to fail`);
  }

  it("gives a position this can read, whichever engine it is", () => {
    // The invariant that matters, and the one the old file meant to hold: a
    // trailing comma is a positioned error everywhere, so a reader is told
    // where to look rather than being shown the engine's English.
    const source = '{"a": 1,}';
    const e = describeJsonError(parseError(source), source);
    expect(e.kind, `this engine's message is not one this file knows`).toBe("positioned");
    expect(e.line).toBe(1);
    expect(e.column).toBe(9);
  });

  it("knows when the text simply ran out", () => {
    const e = describeJsonError(parseError("[1,2,"), "[1,2,");
    expect(e.kind).toBe("truncated");
  });
});
