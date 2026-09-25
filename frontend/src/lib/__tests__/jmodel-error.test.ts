import { describe, it, expect } from "vitest";
import { jmodelErrorLocation, jmodelErrorText } from "@/lib/jmodel-error";
import type { ErrorTranslator } from "@/lib/errors";

const MESSAGES: Record<string, string> = {
  "jmodel.unknown_symbol": "{name} no está declarado.",
  "jmodel.expected_set_member": "Aquí se esperaba un miembro del conjunto, y hay {got}.",
};

const t = Object.assign(
  (key: string, values?: Record<string, string | number>): string =>
    (MESSAGES[key] ?? key).replace(/\{(\w+)\}/g, (_, n) => String(values?.[n] ?? `{${n}}`)),
  { has: (key: string) => key in MESSAGES },
) as ErrorTranslator;

describe("jmodelErrorText", () => {
  it("writes a named failure in the reader's language", () => {
    expect(
      jmodelErrorText(
        { message: "unknown symbol 'y'", code: "jmodel.unknown_symbol", params: { name: "y" } },
        t,
      ),
    ).toBe("y no está declarado.");
  });

  it("fills in what the parser found", () => {
    expect(
      jmodelErrorText(
        {
          message: "expected a set member (identifier or number, got ';')",
          code: "jmodel.expected_set_member",
          params: { got: "';'" },
        },
        t,
      ),
    ).toBe("Aquí se esperaba un miembro del conjunto, y hay ';'.");
  });

  // Most of the compiler's messages carry no code yet; they must still show.
  it("falls back to the compiler's English message when there is no code", () => {
    expect(jmodelErrorText({ message: "term of degree greater than 2", code: null }, t)).toBe(
      "term of degree greater than 2",
    );
  });

  it("falls back when the code has no text in this language", () => {
    expect(jmodelErrorText({ message: "something odd", code: "jmodel.not_translated_yet" }, t)).toBe(
      "something odd",
    );
  });

  it("answers empty for no error at all", () => {
    expect(jmodelErrorText(null, t)).toBe("");
  });
});

describe("jmodelErrorLocation", () => {
  const tStudio = (key: string, values: Record<string, number>) =>
    key === "jmodelErrorAt" ? `línea ${values.line}, columna ${values.column}` : key;

  // The editor printed "(pos 712)", and a reader had to count characters to
  // find the line (found driving the studio, 2026-09-24).
  it("says the line and the column, in the reader's language", () => {
    expect(
      jmodelErrorLocation(
        { message: "unknown symbol 'qq'", position: 30, line: 2, column: 19 },
        tStudio,
      ),
    ).toBe("línea 2, columna 19");
  });

  it("says nothing for an error that points at no place", () => {
    expect(jmodelErrorLocation({ message: "model has no objective", position: null }, tStudio)).toBe(
      null,
    );
    expect(jmodelErrorLocation(null, tStudio)).toBe(null);
  });

  it("never falls back to the raw offset", () => {
    expect(jmodelErrorLocation({ message: "x", position: 712 }, tStudio)).toBe(null);
  });
});
