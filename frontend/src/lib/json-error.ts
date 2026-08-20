/**
 * Turn a `JSON.parse` failure into something worth showing a reader.
 *
 * The engine's own message is English and is written for a developer, and one
 * of its shapes quotes the broken text back at the person who typed it:
 *
 *   Unexpected token 'a', "{"sets": [a,b,c }" is not valid JSON
 *
 * That sentence went straight into a toast inside a Spanish page. The only part
 * of it a reader can act on is WHERE the text stopped making sense, so this
 * pulls that out and leaves the wording to the caller's own translations.
 *
 * **Every engine words this differently, and the same engine changed its mind.**
 * The first version of this file read one shape — the one V8 produces from
 * node 24 onwards — and returned "unknown" for everything else. Which meant it
 * worked on the machine it was written on and nowhere else. The build has since
 * moved to node 24, but that is not what makes this safe: the parsing happens
 * in the READER's browser, which may be Firefox, or Safari, or a Chrome a year
 * old. All four shapes below are handled:
 *
 *   V8, node 24+ / recent Chromium
 *     {"a": 1,}     Expected double-quoted property name in JSON at position 8 (line 1 column 9)
 *   V8, before node 24 / older Chromium — a byte offset and no line
 *     {"a": 1,}     Unexpected token } in JSON at position 8
 *   SpiderMonkey (Firefox) — a line and column, without the parentheses
 *     {"a": 1,}     JSON.parse: expected double-quoted property name at line 1 column 9 of the JSON data
 *   JavaScriptCore (Safari) — no position at all
 *     {"a": 1,}     JSON Parse error: Expected '"'
 *
 * A byte offset becomes a line and a column only if the caller hands over the
 * text it tried to parse. Without it the offset says nothing a reader can use,
 * so the answer is "unknown" rather than a number pointing into thin air.
 *
 * Two failures carry no position on any engine, and they mean different things:
 * text that stops early is almost always a bracket left open, and saying so is
 * more use than "invalid".
 */

export type JsonErrorKind = "positioned" | "truncated" | "unknown";

export interface JsonError {
  kind: JsonErrorKind;
  /** 1-based, only on `positioned`. */
  line: number | null;
  /** 1-based, only on `positioned`. */
  column: number | null;
}

/** V8 from node 24: "… at position 8 (line 1 column 9)". */
const PARENS_RE = /\(line (\d+) column (\d+)\)/;
/** SpiderMonkey: "… at line 1 column 9 of the JSON data". */
const BARE_RE = /\bat line (\d+) column (\d+)/;
/** V8 before node 24: "… in JSON at position 8" — an offset into the text. */
const OFFSET_RE = /\bat position (\d+)/;

const UNKNOWN: JsonError = { kind: "unknown", line: null, column: null };

/** Where offset `n` falls in `source`, counted the way every engine counts: 1-based. */
function locate(source: string, n: number): JsonError {
  // Past the end means the text ran out rather than went wrong somewhere.
  if (n > source.length) return { kind: "truncated", line: null, column: null };
  const upTo = source.slice(0, n);
  const lastBreak = upTo.lastIndexOf("\n");
  return {
    kind: "positioned",
    line: (upTo.match(/\n/g)?.length ?? 0) + 1,
    column: n - lastBreak,
  };
}

/**
 * @param err    whatever `JSON.parse` threw.
 * @param source the text it was given. Only needed on the engines that report a
 *               byte offset instead of a line and column, but pass it always —
 *               which engine the reader is on is not something the caller knows.
 */
export function describeJsonError(err: unknown, source?: string): JsonError {
  const message = err instanceof Error ? err.message : String(err);

  // "Unexpected end of JSON input" — the text ran out mid-value. Checked before
  // the position shapes because node 24 gives this one an offset too, and a
  // bracket left open is worth its own sentence.
  if (/end of (?:JSON )?input|end of data|Unexpected EOF/i.test(message)) {
    return { kind: "truncated", line: null, column: null };
  }

  const parens = PARENS_RE.exec(message);
  if (parens) {
    return { kind: "positioned", line: Number(parens[1]), column: Number(parens[2]) };
  }

  const bare = BARE_RE.exec(message);
  if (bare) {
    return { kind: "positioned", line: Number(bare[1]), column: Number(bare[2]) };
  }

  const offset = OFFSET_RE.exec(message);
  if (offset && typeof source === "string") {
    return locate(source, Number(offset[1]));
  }

  return UNKNOWN;
}
