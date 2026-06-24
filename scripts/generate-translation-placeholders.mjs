#!/usr/bin/env node
/**
 * Generate placeholder translation files from en.json.
 *
 * Usage:
 *   node scripts/generate-translation-placeholders.mjs           # all missing locales
 *   node scripts/generate-translation-placeholders.mjs fr de     # specific locales only
 *   node scripts/generate-translation-placeholders.mjs --force   # overwrite existing files
 *
 * Output: frontend/messages/<locale>.json for each locale.
 *
 * Placeholder format:
 *   "[CA] Loading..."        — needs translation
 *   "{count, plural, ...}"   — ICU strings are copied verbatim (translate manually)
 *
 * Keys whose English value is a brand name, URL, or technical token are copied as-is
 * (no prefix) so they don't need translation.
 */

import { readFileSync, writeFileSync, existsSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MESSAGES_DIR = join(__dirname, "..", "frontend", "messages");
const EN_PATH = join(MESSAGES_DIR, "en.json");

const ALL_LOCALES = [
  "ca", "fr", "de",
  "it", "pt", "nl", "pl",
  "ro", "el", "cs", "sv",
  "da", "fi", "hu", "ru",
];

// Brand names, technical tokens, etc. — copied verbatim.
const VERBATIM_PATTERNS = [
  /^JAOT$/,
  /^SCIP$/,
  /^https?:\/\//,
  /^[A-Z_]{2,}$/,              // env-var-style tokens
  /^\{[^}]+\}$/,               // pure ICU variable like "{name}"
  /^#$/,
  /^\/\w/,                      // paths like "/mo"
];

const ICU_PATTERN = /\{.+,\s*(?:plural|select|selectordinal)\s*,/;

function isVerbatim(value) {
  return VERBATIM_PATTERNS.some((p) => p.test(value));
}

function prefixValue(value, locale) {
  if (typeof value !== "string") return value;
  if (isVerbatim(value)) return value;
  if (ICU_PATTERN.test(value)) return `[${locale.toUpperCase()}] ${value}`;
  return `[${locale.toUpperCase()}] ${value}`;
}

function transformTree(obj, locale) {
  if (typeof obj === "string") return prefixValue(obj, locale);
  if (Array.isArray(obj)) return obj.map((v) => transformTree(v, locale));
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = transformTree(v, locale);
  }
  return out;
}

const args = process.argv.slice(2);
const force = args.includes("--force");
const requestedLocales = args.filter((a) => !a.startsWith("--"));
const locales = requestedLocales.length > 0 ? requestedLocales : ALL_LOCALES;

const en = JSON.parse(readFileSync(EN_PATH, "utf-8"));

let created = 0;
let skipped = 0;

for (const locale of locales) {
  const outPath = join(MESSAGES_DIR, `${locale}.json`);
  if (existsSync(outPath) && !force) {
    console.log(`  SKIP  ${locale}.json (exists, use --force to overwrite)`);
    skipped++;
    continue;
  }
  const translated = transformTree(en, locale);
  writeFileSync(outPath, JSON.stringify(translated, null, 2) + "\n", "utf-8");
  console.log(`  WRITE ${locale}.json`);
  created++;
}

console.log(`\nDone: ${created} created, ${skipped} skipped.`);
console.log(`\nNext steps:`);
console.log(`  1. Open each <locale>.json file`);
console.log(`  2. Replace "[XX] English text" with the real translation`);
console.log(`  3. For ICU plural strings, translate the text AND adjust plural categories`);
console.log(`     (e.g. Polish needs one/few/many/other, Russian needs one/few/many/other)`);
console.log(`  4. Run: node scripts/validate-i18n-plurals.mjs`);
