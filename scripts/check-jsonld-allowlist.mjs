#!/usr/bin/env node

/**
 * JSON-LD @type Allowlist Checker (SC4)
 *
 * Scans schema builder files and public-route source files for forbidden
 * JSON-LD @type values: FAQPage, Review, AggregateRating.
 *
 * These types are forbidden because:
 *   - FAQPage / Review: require genuine first-party content; using them without
 *     verified reviews/FAQs triggers Google manual-action policy violations.
 *   - AggregateRating: using activation counts as reviewCount (former codebase
 *     pattern, D-02) is a fake-review signal that risks a Google manual action.
 *
 * Matching strategy: only flags the tokens when they appear as quoted string
 * literals in a @type assignment context (e.g. "@type": "AggregateRating" or
 * "@type": "Review"). Bare tokens in comments, variable names, or prose
 * do NOT trigger violations — the pattern requires the token to be a quoted
 * value following a @type key.
 *
 * Usage: node scripts/check-jsonld-allowlist.mjs
 * Exit code 0 = clean, 1 = violations found
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const FORBIDDEN_TYPES = ["FAQPage", "Review", "AggregateRating"];

// Repo-root-relative scan paths (resolved relative to this script's location)
const REPO_ROOT = join(import.meta.dirname, "..");
// Plan 04 (Wave 2) extended scan paths: now that the inline AggregateRating block has been
// removed from marketplace/[modelId]/page.tsx (D-02 cleanup), the public-route tree is clean
// and the scan is extended to include it. This makes the gate enforce the allowlist policy on
// routes directly — not just on builders — as intended by SC4.
const SCAN_PATHS = [
  // Schema builders — source-of-truth for all JSON-LD @type values emitted via <JsonLd>.
  join(REPO_ROOT, "frontend", "src", "lib", "seo", "schemas"),
  // SEO component — catches any @type values bypassed at the <JsonLd> component level.
  join(REPO_ROOT, "frontend", "src", "components", "seo"),
  // Public route tree — catches re-introduction of forbidden @type in route files (Plan 04+).
  // The AggregateRating inline block that blocked this scan in Wave-0 (Plan 03) has been
  // removed in Plan 04 (D-02). This path is now load-bearing: SC4 enforcement on routes.
  join(REPO_ROOT, "frontend", "src", "app", "[locale]", "(public)"),
];

const SCANNABLE_EXTENSIONS = new Set([".ts", ".tsx", ".mjs"]);

// Single regex matching any forbidden type as the quoted value of a @type key.
// MUST match:    "@type": "AggregateRating"   { "@type": "FAQPage" }   @type: "Review"
// MUST NOT match: // Review the output   reviewCount: 5   const reviewId   "averageRating"
// Pattern: `@type` (optional quotes on the key) + ws + colon + ws + the forbidden token as a
// quoted string. Built from FORBIDDEN_TYPES so adding a type is a one-line change; the capture
// group reports which type matched.
const FORBIDDEN_RE = new RegExp(
  `"?@type"?\\s*:\\s*"(${FORBIDDEN_TYPES.join("|")})"`,
  "g",
);

let violations = 0;

/**
 * Recursively walk a directory and scan every file with a scannable extension.
 * Skips the directory silently if it does not exist (makes the script safe to
 * run from either repo root or frontend/).
 */
function scanDir(dirPath) {
  let entries;
  try {
    entries = readdirSync(dirPath);
  } catch {
    // Directory does not exist — skip silently
    return;
  }

  for (const entry of entries) {
    const fullPath = join(dirPath, entry);
    let stat;
    try {
      stat = statSync(fullPath);
    } catch {
      continue;
    }

    if (stat.isDirectory()) {
      if (entry === "__tests__") continue;
      scanDir(fullPath);
    } else if (stat.isFile() && SCANNABLE_EXTENSIONS.has(extname(entry)) && !entry.includes(".test.")) {
      scanFile(fullPath);
    }
  }
}

/**
 * Scan a single file for forbidden @type values.
 */
function scanFile(filePath) {
  let content;
  try {
    content = readFileSync(filePath, "utf-8");
  } catch {
    return;
  }

  for (const match of content.matchAll(FORBIDDEN_RE)) {
    const lineNumber = content.slice(0, match.index).split("\n").length;
    console.error(
      `VIOLATION: forbidden @type "${match[1]}" at ${filePath}:${lineNumber}`,
    );
    console.error(`  Matched: ${match[0].trim()}`);
    violations++;
  }
}

for (const scanPath of SCAN_PATHS) {
  scanDir(scanPath);
}

if (violations > 0) {
  console.error(`\nFAILED: ${violations} forbidden @type value(s) found.`);
  process.exit(1);
} else {
  console.log("PASSED: No forbidden JSON-LD @type values found.");
  process.exit(0);
}
