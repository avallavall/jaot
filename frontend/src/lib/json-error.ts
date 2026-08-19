/**
 * Turn a `JSON.parse` failure into something worth showing a reader.
 *
 * The engine's own message is English and is written for a developer, and one
 * of its shapes quotes the broken text back at the person who typed it:
 *
 *   Unexpected token 'a', "{"sets": [a,b,c }" is not valid JSON
 *
 * That sentence went straight into a toast inside a Spanish page. The only part
 * of it a reader can act on is WHERE the text stopped making sense, and V8 does
 * give that in most cases, so this pulls it out and leaves the wording to the
 * caller's own translations.
 *
 * Measured on V8 (node 24, and the same engine in Chromium):
 *
 *   {"a": 1,}       Expected double-quoted property name in JSON at position 8 (line 1 column 9)
 *   {               Expected property name or '}' in JSON at position 1 (line 1 column 2)
 *   {"a" 1}         Expected ':' after property name in JSON at position 5 (line 1 column 6)
 *   [1,2,           Unexpected end of JSON input
 *   {"sets": [a,b,c }   Unexpected token 'a', "…" is not valid JSON
 *
 * The last two carry no position, and the two cases mean different things to a
 * reader: text that stops early is usually a bracket left open.
 */

export type JsonErrorKind = "positioned" | "truncated" | "unknown";

export interface JsonError {
  kind: JsonErrorKind;
  /** 1-based, only on `positioned`. */
  line: number | null;
  /** 1-based, only on `positioned`. */
  column: number | null;
}

const POSITION_RE = /\(line (\d+) column (\d+)\)/;

export function describeJsonError(err: unknown): JsonError {
  const message = err instanceof Error ? err.message : String(err);

  const match = POSITION_RE.exec(message);
  if (match) {
    return { kind: "positioned", line: Number(match[1]), column: Number(match[2]) };
  }
  // "Unexpected end of JSON input" — the text ran out mid-value. Worth saying on
  // its own, because the fix is almost always a bracket or a quote left open,
  // and there is no position to point at.
  if (/end of (?:JSON )?input/i.test(message)) {
    return { kind: "truncated", line: null, column: null };
  }
  return { kind: "unknown", line: null, column: null };
}
