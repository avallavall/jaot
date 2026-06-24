import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const MESSAGES_DIR = path.resolve(__dirname, "../../messages");
const EXPECTED_LOCALES = ["en", "es", "ca", "fr", "de"];

const EXPECTED_GLOSSARY_TERMS = [
  "shadowPrice", "bindingConstraint", "slackValue", "paretoFront",
  "warmStart", "lpRelaxation", "objectiveValue", "baseCost",
  "variableCost", "integerPenalty", "constraintCost", "timeBonus",
  "formulation", "decisionVariable", "constraint", "objective",
  "feasibility", "infeasible", "optimal", "relaxation",
  "seeFormula", "hideFormula",
];

function getLeafKeys(obj: Record<string, unknown>, prefix = ""): string[] {
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      keys.push(...getLeafKeys(v as Record<string, unknown>, fullKey));
    } else {
      keys.push(fullKey);
    }
  }
  return keys.sort();
}

function loadLocale(locale: string): Record<string, unknown> {
  const filePath = path.join(MESSAGES_DIR, `${locale}.json`);
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

describe("glossary i18n completeness (I18N-10)", () => {
  const enData = loadLocale("en");
  const enGlossary = enData.glossary as Record<string, unknown>;

  it("English glossary namespace exists with 22 top-level terms", () => {
    expect(enGlossary).toBeDefined();
    const topKeys = Object.keys(enGlossary);
    expect(topKeys.length).toBe(22);
  });

  it("English glossary has 35 leaf keys", () => {
    const leafKeys = getLeafKeys(enGlossary);
    expect(leafKeys.length).toBe(35);
  });

  it("English glossary contains all expected terms", () => {
    const topKeys = Object.keys(enGlossary);
    for (const term of EXPECTED_GLOSSARY_TERMS) {
      expect(topKeys, `Missing glossary term: ${term}`).toContain(term);
    }
  });

  it.each(EXPECTED_LOCALES.filter((l) => l !== "en"))(
    "%s.json glossary has same 35 leaf keys as en.json",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeGlossary = localeData.glossary as Record<string, unknown>;
      expect(localeGlossary, `${locale} missing glossary namespace`).toBeDefined();

      const enLeafKeys = getLeafKeys(enGlossary);
      const localeLeafKeys = getLeafKeys(localeGlossary);

      expect(localeLeafKeys.length).toBe(35);

      const missing = enLeafKeys.filter((k) => !localeLeafKeys.includes(k));
      expect(
        missing.length,
        `${locale} glossary missing keys: ${missing.join(", ")}`
      ).toBe(0);
    }
  );

  it.each(EXPECTED_LOCALES.filter((l) => l !== "en"))(
    "%s.json glossary values are non-empty strings",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeGlossary = localeData.glossary as Record<string, unknown>;
      const leafKeys = getLeafKeys(localeGlossary);

      for (const key of leafKeys) {
        const parts = key.split(".");
        let value: unknown = localeGlossary;
        for (const part of parts) {
          value = (value as Record<string, unknown>)[part];
        }
        expect(
          typeof value === "string" && value.length > 0,
          `${locale} glossary key "${key}" is empty or not a string`
        ).toBe(true);
      }
    }
  );
});
