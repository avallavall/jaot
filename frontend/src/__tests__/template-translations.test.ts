import { describe, it, expect } from "vitest";
import en from "../../messages/en.json";

const EXPECTED_TEMPLATE_COUNT = 101;
const EXPECTED_CATEGORY_COUNT = 34;
const REQUIRED_FIELDS = [
  "displayName",
  "shortDescription",
  "description",
  "scenarioDescription",
  "categoryDisplayName",
] as const;

describe("template-translations", () => {
  const templates = (en as Record<string, unknown>).templates as Record<
    string,
    Record<string, string>
  >;

  it("templates namespace exists in en.json", () => {
    expect(templates).toBeDefined();
    expect(typeof templates).toBe("object");
  });

  it(`has ${EXPECTED_TEMPLATE_COUNT} template entries`, () => {
    const templateKeys = Object.keys(templates).filter(
      (k) => !k.startsWith("_")
    );
    expect(templateKeys.length).toBe(EXPECTED_TEMPLATE_COUNT);
  });

  it(`has ${EXPECTED_CATEGORY_COUNT} category entries in _categories`, () => {
    const categories = templates._categories;
    expect(categories).toBeDefined();
    expect(Object.keys(categories).length).toBe(EXPECTED_CATEGORY_COUNT);
  });

  it("each template has all 5 required fields", () => {
    const templateKeys = Object.keys(templates).filter(
      (k) => !k.startsWith("_")
    );
    for (const tid of templateKeys) {
      const entry = templates[tid];
      for (const field of REQUIRED_FIELDS) {
        expect(
          entry[field],
          `Template "${tid}" missing field "${field}"`
        ).toBeDefined();
      }
    }
  });

  it("no empty string values in template entries", () => {
    const templateKeys = Object.keys(templates).filter(
      (k) => !k.startsWith("_")
    );
    for (const tid of templateKeys) {
      const entry = templates[tid];
      for (const field of REQUIRED_FIELDS) {
        expect(
          entry[field].length,
          `Template "${tid}" has empty "${field}"`
        ).toBeGreaterThan(0);
      }
    }
  });

  it("no empty string values in _categories", () => {
    const categories = templates._categories;
    for (const [key, value] of Object.entries(categories)) {
      expect(
        (value as string).length,
        `Category "${key}" has empty display name`
      ).toBeGreaterThan(0);
    }
  });

  it("template IDs use snake_case", () => {
    const templateKeys = Object.keys(templates).filter(
      (k) => !k.startsWith("_")
    );
    for (const tid of templateKeys) {
      expect(
        tid,
        `Template ID "${tid}" should be snake_case`
      ).toMatch(/^[a-z][a-z0-9_]*$/);
    }
  });
});
