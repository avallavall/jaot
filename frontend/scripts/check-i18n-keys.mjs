#!/usr/bin/env node
/**
 * Scan all source files for `useTranslations(ns)` + `t("key")` calls and
 * verify every resolved key (`ns.key`) exists in every locale JSON.
 *
 * Designed to catch MISSING_MESSAGE bugs at build/test time instead of
 * letting them surface as raw keys in production toasts.
 *
 * Exit codes:
 *   0 — all keys covered in all locales
 *   1 — missing keys (printed grouped by file)
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = join(__dirname, "..");
const SRC_ROOT = join(FRONTEND_ROOT, "src");
const MESSAGES_ROOT = join(FRONTEND_ROOT, "messages");
const LOCALES = ["en", "es", "ca", "fr", "de"];

/** Walk a directory recursively for .ts/.tsx source files. */
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules") continue;
    if (entry.name === ".next") continue;
    if (entry.name === "__tests__") continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry.name)) continue;
    if (entry.name.endsWith(".d.ts")) continue;
    if (entry.name.includes(".test.") || entry.name.includes(".spec.")) continue;
    out.push(full);
  }
  return out;
}

/** Flatten a nested locale JSON object into a Set of dot-paths. */
function flatten(obj, prefix = "") {
  const out = new Set();
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const inner of flatten(v, key)) out.add(inner);
    } else {
      out.add(key);
    }
  }
  return out;
}

/** Extract `useTranslations(ns)` calls and their assigned variable names. */
function findNamespaces(src) {
  const namespaces = {};
  // const t = useTranslations("ns")
  // const tFoo = useTranslations("ns")
  // const t = useTranslations()
  const re = /const\s+(\w+)\s*=\s*useTranslations\(\s*(?:["'`]([^"'`]*)["'`])?\s*\)/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    namespaces[m[1]] = m[2] ?? "";
  }
  return namespaces;
}

/** Extract `await getTranslations({ locale, namespace: "ns" })` calls (server components). */
function findServerNamespaces(src) {
  const namespaces = {};
  // const t = await getTranslations({ locale, namespace: "ns" })
  // property order inside the object literal is tolerated (namespace may appear before locale)
  const re =
    /const\s+(\w+)\s*=\s*await\s+getTranslations\(\s*\{[^}]*namespace\s*:\s*["'`]([^"'`]+)["'`][^}]*\}\s*\)/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    namespaces[m[1]] = m[2];
  }
  return namespaces;
}

/**
 * Detect `buildPageMetadata({ namespace: "ns", ... })` calls.
 *
 * buildPageMetadata always calls `t("title")` and `t("description")` with the
 * provided namespace, so we synthesize two keys per occurrence: `ns.title` and
 * `ns.description`. Returns them as pre-resolved full keys (not as a varName map)
 * since there is no intermediate `t` variable here.
 *
 * @returns {string[]} Array of fully-qualified key paths to verify.
 */
function findBuildMetadataKeys(src) {
  const keys = [];
  // buildPageMetadata({ namespace: "metadata.pricing", ... })
  // also matches multi-line calls where namespace appears on a separate line
  const re = /buildPageMetadata\(\s*\{[^}]*namespace\s*:\s*["'`]([^"'`]+)["'`]/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    const ns = m[1];
    keys.push(`${ns}.title`);
    keys.push(`${ns}.description`);
  }
  return keys;
}

/**
 * Find all `varName("key")` and `varName.rich("key")` calls.
 *
 * Returns two buckets:
 *  - `staticKeys`: keys with no `${...}` interpolation (fully resolvable)
 *  - `dynamicPrefixes`: keys built from template literals; we can only verify
 *    their static prefix exists as an object path in the locale.
 */
function findKeyCalls(src, varName) {
  const staticKeys = [];
  const dynamicPrefixes = [];
  const escaped = varName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(
    `\\b${escaped}(?:\\.\\w+)?\\(\\s*["'\`]([^"'\`]+)["'\`]`,
    "g",
  );
  let m;
  while ((m = re.exec(src)) !== null) {
    const raw = m[1];
    if (raw.includes("${")) {
      const prefix = raw.slice(0, raw.indexOf("${")).replace(/\.$/, "");
      if (prefix) dynamicPrefixes.push(prefix);
    } else {
      staticKeys.push(raw);
    }
  }
  return { staticKeys, dynamicPrefixes };
}

/**
 * Check whether a dynamic prefix has at least one matching key in the locale.
 *
 * Accepts both forms:
 *   - Dot-separated: `t(\`foo.bar.${x}\`)` matches `foo.bar.baz`
 *   - Concatenation: `t(\`foo.days${n}\`)` matches `foo.days7`
 */
function prefixExists(localeKeys, prefix) {
  for (const k of localeKeys) {
    if (k === prefix) return true;
    if (k.length > prefix.length && k.startsWith(prefix)) {
      const next = k[prefix.length];
      // Next char is either a path separator (intermediate node) or
      // alphanumeric (concatenation appended directly to the prefix).
      if (next === "." || /\w/.test(next)) return true;
    }
  }
  return false;
}

function loadLocale(locale) {
  const path = join(MESSAGES_ROOT, `${locale}.json`);
  return flatten(JSON.parse(readFileSync(path, "utf8")));
}

function main() {
  const localeKeys = Object.fromEntries(
    LOCALES.map((l) => [l, loadLocale(l)]),
  );

  const files = walk(SRC_ROOT);
  /** @type {Array<{file: string, key: string, missingIn: string[], kind: "static"|"dynamic"}>} */
  const issues = [];

  for (const file of files) {
    const src = readFileSync(file, "utf8");
    const namespaces = { ...findNamespaces(src), ...findServerNamespaces(src) };
    const fileRel = relative(FRONTEND_ROOT, file).replace(/\\/g, "/");

    // Check keys resolved through buildPageMetadata({ namespace: "ns" }) calls.
    // buildPageMetadata always emits t("title") + t("description") for the given namespace.
    const buildMetaKeys = findBuildMetadataKeys(src);
    for (const fullKey of buildMetaKeys) {
      const missingIn = LOCALES.filter((l) => !localeKeys[l].has(fullKey));
      if (missingIn.length > 0) {
        issues.push({ file: fileRel, key: fullKey, missingIn, kind: "static" });
      }
    }

    if (Object.keys(namespaces).length === 0) continue;

    for (const [varName, ns] of Object.entries(namespaces)) {
      const { staticKeys, dynamicPrefixes } = findKeyCalls(src, varName);

      // Static keys: must exist verbatim in every locale
      for (const k of staticKeys) {
        const fullKey = ns ? `${ns}.${k}` : k;
        const missingIn = LOCALES.filter((l) => !localeKeys[l].has(fullKey));
        if (missingIn.length > 0) {
          issues.push({ file: fileRel, key: fullKey, missingIn, kind: "static" });
        }
      }

      // Dynamic keys (template literals): we can only check that the static
      // prefix resolves to an object node in every locale.
      for (const p of dynamicPrefixes) {
        const fullPrefix = ns ? `${ns}.${p}` : p;
        const missingIn = LOCALES.filter((l) => !prefixExists(localeKeys[l], fullPrefix));
        if (missingIn.length > 0) {
          issues.push({
            file: fileRel,
            key: `${fullPrefix}.*`,
            missingIn,
            kind: "dynamic",
          });
        }
      }
    }
  }

  // Dedupe by (file, key)
  const seen = new Set();
  const unique = issues.filter((i) => {
    const k = `${i.file}|${i.key}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  if (unique.length === 0) {
    console.log("i18n coverage: OK — all keys present in all locales");
    process.exit(0);
  }

  // Group by file for readable output
  /** @type {Record<string, Array<{key: string, missingIn: string[]}>>} */
  const byFile = {};
  for (const i of unique) {
    if (!byFile[i.file]) byFile[i.file] = [];
    byFile[i.file].push({ key: i.key, missingIn: i.missingIn });
  }

  console.error(`i18n coverage FAILED: ${unique.length} missing key(s)\n`);
  for (const [file, keys] of Object.entries(byFile)) {
    console.error(file);
    for (const { key, missingIn } of keys) {
      const all = missingIn.length === LOCALES.length;
      const where = all ? "all locales" : missingIn.join(",");
      console.error(`  ${key}  (missing in ${where})`);
    }
    console.error("");
  }
  process.exit(1);
}

main();
