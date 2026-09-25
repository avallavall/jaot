import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { solverErrorText } from "@/lib/solver-error";
import type { ErrorTranslator } from "@/lib/errors";

type Catalogue = Record<string, unknown>;

function messages(locale: string): Catalogue {
  const path = resolve(__dirname, `../../../messages/${locale}.json`);
  return JSON.parse(readFileSync(path, "utf8")) as Catalogue;
}

/** A translator over `errors.codes` of one locale, with next-intl's `{name}` filling. */
function translator(locale: string): ErrorTranslator {
  const codes = (messages(locale).errors as Catalogue).codes as Catalogue;
  const lookup = (key: string): string | undefined => {
    let node: unknown = codes;
    for (const part of key.split(".")) {
      node = node && typeof node === "object" ? (node as Catalogue)[part] : undefined;
    }
    return typeof node === "string" ? node : undefined;
  };
  const t = ((key: string, values?: Record<string, string | number>) =>
    Object.entries(values ?? {}).reduce(
      (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
      lookup(key) ?? key,
    )) as ErrorTranslator;
  t.has = (key: string) => lookup(key) !== undefined;
  return t;
}

const ENGLISH =
  "JAOS in JAOT takes linear models only — quadratic term 'x*x' in the objective. " +
  "Use SCIP (or automatic selection) for quadratic models.";

/**
 * # CONTRACT-TEST: a solver refusal with a code is shown in the reader's language
 *
 * The JAOS refusal of a quadratic model reached the Spanish execution page in
 * English (QA, 2026-09-25).
 */
describe("solverErrorText", () => {
  it("says the JAOS refusal in Spanish", () => {
    const text = solverErrorText(
      {
        error_code: "solver.quadratic_in_objective",
        error_params: { solver: "JAOS", term: "x*x" },
      },
      ENGLISH,
      translator("es"),
    );
    expect(text).not.toBe(ENGLISH);
    expect(text).toContain("JAOS");
    expect(text).toContain("x*x");
    expect(text).toContain("SCIP");
  });

  it("has words for every linear-only code in all five locales", () => {
    const codes = [
      ["solver.linear_only", { solver: "CBC" }],
      ["solver.quadratic_in_objective", { solver: "HiGHS", term: "x*y" }],
      ["solver.quadratic_in_constraint", { solver: "GLPK", term: "x*y", constraint: "c1" }],
    ] as const;
    for (const locale of ["en", "es", "ca", "fr", "de"]) {
      const t = translator(locale);
      for (const [code, params] of codes) {
        expect(t.has(code), `${locale} ${code}`).toBe(true);
        const text = solverErrorText({ error_code: code, error_params: params }, ENGLISH, t);
        for (const value of Object.values(params)) {
          expect(text, `${locale} ${code}`).toContain(value);
        }
        expect(text, `${locale} ${code} left a placeholder`).not.toMatch(/\{\w+\}/);
      }
    }
  });

  it("keeps the English text when there is no code", () => {
    expect(solverErrorText({ error_code: null }, ENGLISH, translator("es"))).toBe(ENGLISH);
    expect(solverErrorText(undefined, ENGLISH, translator("es"))).toBe(ENGLISH);
  });

  it("keeps the English text for a code this build has no words for", () => {
    expect(
      solverErrorText({ error_code: "solver.not_a_code_yet" }, ENGLISH, translator("es")),
    ).toBe(ENGLISH);
  });
});
