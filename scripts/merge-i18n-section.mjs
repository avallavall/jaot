#!/usr/bin/env node
/**
 * Merges a translated section into a locale's JSON file.
 * Usage: node scripts/merge-i18n-section.mjs <locale> <section> < translated.json
 * Example: echo '{"loading":"Laden..."}' | node scripts/merge-i18n-section.mjs de common
 */
import { readFileSync, writeFileSync } from 'fs';
import { join } from 'path';

const [locale, section, inputFile] = process.argv.slice(2);
if (!locale || !section || !inputFile) {
  console.error('Usage: merge-i18n-section.mjs <locale> <section> <input.json>');
  process.exit(1);
}

const filePath = join('frontend', 'messages', `${locale}.json`);
const existing = JSON.parse(readFileSync(filePath, 'utf-8'));
const input = JSON.parse(readFileSync(inputFile, 'utf-8'));

existing[section] = input;
writeFileSync(filePath, JSON.stringify(existing, null, 2) + '\n', 'utf-8');
console.log(`Merged section "${section}" into ${filePath}`);
