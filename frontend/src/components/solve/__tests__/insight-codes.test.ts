import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * The insight codes the backend can emit, mirrored from
 * `tests/test_insights.py::INSIGHT_CODES` (which asserts the service emits
 * nothing outside its own copy). A code with no text here renders in English,
 * which is the defect this pair of tests exists to prevent.
 */
const INSIGHT_CODES = [
  "objective.optimal_value.maximize",
  "objective.optimal_value.minimize",
  "objective.globally_optimal",
  "objective.feasible_not_proven",
  "objective.infeasible",
  "objective.unbounded",
  "performance.gap_improvable",
  "performance.gap_negligible",
  "performance.solved_fast",
  "performance.solved_slow",
  "variables.at_bounds",
  "variables.zero_valued",
  "variables.type_mix",
  "constraints.binding",
  "constraints.most_impactful",
];

const LOCALES = ["en", "es", "ca", "fr", "de"];

function messages(locale: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(join(process.cwd(), "messages", `${locale}.json`), "utf8"),
  );
}

function at(root: unknown, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (node, key) =>
        node && typeof node === "object"
          ? (node as Record<string, unknown>)[key]
          : undefined,
      root,
    );
}

describe("insight code translations", () => {
  // CONTRACT-TEST: every backend insight code has text in every locale.
  it.each(LOCALES)("%s covers every insight code", (locale) => {
    const m = messages(locale);
    const missing = INSIGHT_CODES.filter(
      (code) => typeof at(m, `solve.insights.codes.${code}`) !== "string",
    );
    expect(missing).toEqual([]);
  });

  it.each(LOCALES)("%s names all four insight categories", (locale) => {
    const m = messages(locale);
    for (const category of ["objective", "constraints", "variables", "performance"]) {
      expect(typeof at(m, `solve.insights.category.${category}`)).toBe("string");
    }
  });

  it.each(LOCALES)("%s names all three variable types", (locale) => {
    const m = messages(locale);
    for (const type of ["binary", "integer", "continuous"]) {
      expect(typeof at(m, `solve.insights.varTypes.${type}`)).toBe("string");
    }
  });
});
