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

  // The absolute count used to be pinned here at 539. That is 101 templates x 5
  // fields plus 34 categories, and there are 102 templates: `assignment` had no
  // entry in any locale and this number was written to match the file rather
  // than the source. The YAML is the source of truth and
  // tests/test_template_translations.py compares every locale to it; what is
  // worth checking here is that the four other locales hold exactly the keys
  // English does.
  // This compared enLeafKeys.length against templateCount * 5 + categoryCount,
  // and both sides were derived from the same object: deleting a template drops
  // the leaf count by 5 and the template count by 1, so they stayed equal.
  // Measured: as shipped 544/544 pass, `assignment` deleted 539/539 pass, three
  // templates deleted 529/529 pass. It was written for the one bug it could not
  // see. Checking each entry's own fields cannot be satisfied that way.
  it("every English template entry holds exactly the five required fields", () => {
    const expected = [...REQUIRED_FIELDS].sort().join(",");
    const wrong: string[] = [];
    for (const [id, entry] of Object.entries(enTemplates)) {
      if (id.startsWith("_")) continue;
      const fields = Object.keys(entry as Record<string, unknown>).sort().join(",");
      if (fields !== expected) wrong.push(`${id}: [${fields}]`);
    }
    expect(wrong).toEqual([]);
  });

  it.each(NON_EN_LOCALES)(
    "%s.json templates namespace holds exactly the keys en.json does",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeTemplates = localeData.templates as Record<string, unknown>;
      expect(
        localeTemplates,
        `${locale} missing templates namespace`
      ).toBeDefined();

      const localeLeafKeys = getLeafKeys(localeTemplates);
      expect(localeLeafKeys.length).toBe(enLeafKeys.length);

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
    "%s.json names every category en.json names",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeTemplates = localeData.templates as Record<string, Record<string, string>>;
      const categories = localeTemplates._categories;
      expect(categories, `${locale} missing _categories`).toBeDefined();
      const enCategories = (enTemplates._categories ?? {}) as Record<string, string>;
      expect(Object.keys(categories).sort()).toEqual(Object.keys(enCategories).sort());
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
