#!/usr/bin/env node

/**
 * ICU Plural Category Validator
 *
 * Reads all JSON translation files from frontend/messages/ and validates
 * that ICU plural patterns include the required categories for each locale.
 *
 * Required plural categories per locale family:
 *   pl, ru, cs:   one, few, many, other
 *   ro:           one, few, other
 *   All others:   one, other
 *
 * Usage: node scripts/validate-i18n-plurals.mjs
 * Exit code 0 = all pass, 1 = errors found
 */

import { readFileSync, readdirSync } from "node:fs";
import { join, basename } from "node:path";

const MESSAGES_DIR = join(import.meta.dirname, "..", "frontend", "messages");

const PLURAL_RULES = {
  pl: ["one", "few", "many", "other"],
  ru: ["one", "few", "many", "other"],
  cs: ["one", "few", "many", "other"],
  ro: ["one", "few", "other"],
};
const DEFAULT_CATEGORIES = ["one", "other"];

/**
 * Recursively walk an object and collect all string values.
 */
function collectStrings(obj, prefix = "") {
  const result = [];
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") {
      result.push({ path, value });
    } else if (value && typeof value === "object") {
      result.push(...collectStrings(value, path));
    }
  }
  return result;
}

/**
 * Extract plural categories from an ICU plural pattern string.
 * Pattern: {varName, plural, one {..} few {..} many {..} other {..}}
 */
function extractPluralCategories(str) {
  const plurals = [];
  // Match ICU plural blocks; nested braces handled via depth counter.
  const pluralRegex = /\{(\w+),\s*plural,\s*/g;
  let match;

  while ((match = pluralRegex.exec(str)) !== null) {
    const startIdx = match.index + match[0].length;
    let depth = 1; // Already inside the outer {
    let idx = startIdx;
    let categoriesStr = "";

    while (idx < str.length && depth > 0) {
      if (str[idx] === "{") depth++;
      else if (str[idx] === "}") depth--;
      if (depth > 0) categoriesStr += str[idx];
      idx++;
    }

    // Category names: one, few, many, other, =0, =1, etc.
    const categoryRegex = /(?:^|\s)(zero|one|two|few|many|other|=\d+)\s*\{/g;
    const categories = [];
    let catMatch;
    while ((catMatch = categoryRegex.exec(categoriesStr)) !== null) {
      categories.push(catMatch[1]);
    }

    plurals.push({
      variable: match[1],
      categories,
      raw: str.substring(match.index, idx),
    });
  }

  return plurals;
}

let errors = 0;
let filesChecked = 0;
let pluralsChecked = 0;

const files = readdirSync(MESSAGES_DIR).filter((f) => f.endsWith(".json"));

for (const file of files) {
  const locale = basename(file, ".json");
  const filePath = join(MESSAGES_DIR, file);
  const content = JSON.parse(readFileSync(filePath, "utf-8"));
  const strings = collectStrings(content);
  const requiredCategories = PLURAL_RULES[locale] || DEFAULT_CATEGORIES;

  filesChecked++;

  for (const { path, value } of strings) {
    if (!value.includes("plural,")) continue;

    const plurals = extractPluralCategories(value);
    for (const plural of plurals) {
      pluralsChecked++;
      const missing = requiredCategories.filter(
        (cat) => !plural.categories.includes(cat)
      );

      if (missing.length > 0) {
        console.error(
          `ERROR [${locale}] ${path}: plural {${plural.variable}} missing categories: ${missing.join(", ")}`
        );
        console.error(`  Required for ${locale}: ${requiredCategories.join(", ")}`);
        console.error(`  Found: ${plural.categories.join(", ")}`);
        errors++;
      }
    }
  }
}

console.log(
  `\nChecked ${filesChecked} file(s), ${pluralsChecked} plural pattern(s).`
);

if (errors > 0) {
  console.error(`\nFAILED: ${errors} error(s) found.`);
  process.exit(1);
} else {
  console.log("PASSED: All plural patterns have required categories.");
  process.exit(0);
}
