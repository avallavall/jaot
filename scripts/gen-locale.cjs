#!/usr/bin/env node
/**
 * Generate a locale translation file from en.json
 * Usage: node gen-locale.cjs <locale> <translations-file>
 *
 * The translations file is a flat JSON object mapping dot-paths to translated strings.
 * Any paths not in the translations file keep the English value.
 */
const fs = require('fs');
const path = require('path');

const locale = process.argv[2];
const transFile = process.argv[3];

if (!locale || !transFile) {
  console.error('Usage: node gen-locale.cjs <locale> <translations-file>');
  process.exit(1);
}

const en = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'messages', 'en.json'), 'utf-8'));
const trans = JSON.parse(fs.readFileSync(transFile, 'utf-8'));

function setPath(obj, pathStr, value) {
  const parts = pathStr.split('.');
  let current = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (!current[parts[i]] || typeof current[parts[i]] !== 'object') current[parts[i]] = {};
    current = current[parts[i]];
  }
  current[parts[parts.length - 1]] = value;
}

function getPath(obj, pathStr) {
  const parts = pathStr.split('.');
  let current = obj;
  for (const part of parts) {
    if (current === undefined || current === null) return undefined;
    current = current[part];
  }
  return current;
}

function collectPaths(obj, prefix = '') {
  const result = [];
  for (const [key, value] of Object.entries(obj)) {
    const p = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      result.push(p);
    } else if (value && typeof value === 'object' && !Array.isArray(value)) {
      result.push(...collectPaths(value, p));
    }
  }
  return result;
}

const result = JSON.parse(JSON.stringify(en));

const allPaths = collectPaths(en);
let translated = 0;
let kept = 0;

for (const p of allPaths) {
  if (trans[p] !== undefined) {
    setPath(result, p, trans[p]);
    translated++;
  } else {
    kept++;
  }
}

const outPath = path.join(__dirname, '..', 'frontend', 'messages', `${locale}.json`);
fs.writeFileSync(outPath, JSON.stringify(result, null, 2) + '\n');
console.log(`Wrote ${outPath}: ${translated} translated, ${kept} kept as English`);
