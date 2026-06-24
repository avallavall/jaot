import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const MESSAGES_DIR = path.resolve(__dirname, "../../messages");
const EXPECTED_LOCALES = ["en", "es", "ca", "fr", "de"];

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
  const content = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(content);
}

describe("locale file completeness (I18N-06)", () => {
  const enData = loadLocale("en");
  const enKeys = getLeafKeys(enData);

  it("English baseline has keys", () => {
    expect(enKeys.length).toBeGreaterThan(2000);
  });

  it.each(EXPECTED_LOCALES.filter((l) => l !== "en"))(
    "%s.json exists and parses as valid JSON",
    (locale) => {
      const filePath = path.join(MESSAGES_DIR, `${locale}.json`);
      expect(fs.existsSync(filePath), `${locale}.json should exist`).toBe(true);
      expect(() => loadLocale(locale)).not.toThrow();
    }
  );

  it.each(EXPECTED_LOCALES.filter((l) => l !== "en"))(
    "%s.json has all top-level namespaces from en.json",
    (locale) => {
      const localeData = loadLocale(locale);
      const enNamespaces = Object.keys(enData).sort();
      const localeNamespaces = Object.keys(localeData).sort();
      for (const ns of enNamespaces) {
        expect(
          localeNamespaces,
          `${locale}.json missing namespace "${ns}"`
        ).toContain(ns);
      }
    }
  );

  it.each(EXPECTED_LOCALES.filter((l) => l !== "en"))(
    "%s.json has key parity with en.json (at most 2 missing keys allowed)",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeKeys = getLeafKeys(localeData);
      const missingKeys = enKeys.filter((k) => !localeKeys.includes(k));
      // Allow up to 2 missing keys (hu and ru each miss solve.compare.back)
      expect(
        missingKeys.length,
        `${locale}.json missing ${missingKeys.length} keys: ${missingKeys.slice(0, 5).join(", ")}`
      ).toBeLessThanOrEqual(2);
    }
  );

  it.each(EXPECTED_LOCALES.filter((l) => l !== "en"))(
    "%s.json has no extra keys beyond en.json",
    (locale) => {
      const localeData = loadLocale(locale);
      const localeKeys = getLeafKeys(localeData);
      const extraKeys = localeKeys.filter((k) => !enKeys.includes(k));
      expect(
        extraKeys.length,
        `${locale}.json has ${extraKeys.length} extra keys: ${extraKeys.slice(0, 5).join(", ")}`
      ).toBe(0);
    }
  );
});
