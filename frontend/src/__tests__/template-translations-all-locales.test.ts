import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const MESSAGES_DIR = path.resolve(__dirname, "../../messages");
const NON_EN_LOCALES = ["es", "ca", "fr", "de"];

const REQUIRED_FIELDS = [
  "displayName",
  "shortDescription",
  "description",
  "scenarioDescription",
  "categoryDisplayName",
] as const;

function loadLocale(locale: string): Record<string, unknown> {
  const filePath = path.join(MESSAGES_DIR, `${locale}.json`);
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

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

describe("template translations across all locales (I18N-11)", () => {
  const enData = loadLocale("en");
  const enTemplates = enData.templates as Record<string, unknown>;
  const enLeafKeys = getLeafKeys(enTemplates);

  it("English baseline has 539 template leaf keys", () => {
    expect(enLeafKeys.length).toBe(539);
  });

  it.each(NON_EN_LOCALES)(
    "%s.json templates namespace has 539 leaf keys matching en.json",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeTemplates = localeData.templates as Record<string, unknown>;
      expect(
        localeTemplates,
        `${locale} missing templates namespace`
      ).toBeDefined();

      const localeLeafKeys = getLeafKeys(localeTemplates);
      expect(localeLeafKeys.length).toBe(539);

      const missing = enLeafKeys.filter((k) => !localeLeafKeys.includes(k));
      expect(
        missing.length,
        `${locale} templates missing ${missing.length} keys: ${missing.slice(0, 5).join(", ")}`
      ).toBe(0);

      const extra = localeLeafKeys.filter((k) => !enLeafKeys.includes(k));
      expect(
        extra.length,
        `${locale} templates has ${extra.length} extra keys: ${extra.slice(0, 5).join(", ")}`
      ).toBe(0);
    }
  );

  it.each(NON_EN_LOCALES)(
    "%s.json has _categories with 34 entries",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeTemplates = localeData.templates as Record<string, Record<string, string>>;
      const categories = localeTemplates._categories;
      expect(categories, `${locale} missing _categories`).toBeDefined();
      expect(Object.keys(categories).length).toBe(34);
    }
  );

  it.each(NON_EN_LOCALES)(
    "%s.json templates have no empty string values",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeTemplates = localeData.templates as Record<string, Record<string, string>>;
      const templateKeys = Object.keys(localeTemplates).filter(
        (k) => !k.startsWith("_")
      );
      let emptyCount = 0;
      for (const tid of templateKeys) {
        const entry = localeTemplates[tid];
        for (const field of REQUIRED_FIELDS) {
          if (!entry[field] || entry[field].length === 0) {
            emptyCount++;
          }
        }
      }
      expect(
        emptyCount,
        `${locale} has ${emptyCount} empty template field values`
      ).toBe(0);
    }
  );
});
