#!/usr/bin/env node
/**
 * Print the LOCAL gate baseline (median per URL) from an `lhci collect` run against
 * `lighthouserc-gate.json`. Phase 13.4 Plan 04 Task 2 (D-05): the LOCAL build baseline must be
 * captured in the SAME environment the gate asserts in (the `lhci-gate` CI step:
 * alpine + chromium). `lhci assert` only prints *breaching* metrics; this prints LCP/TBT/CLS/
 * SEO/A11Y for EVERY gated URL so the operator can bake the baseline-relative budget in Plan 05.
 *
 * Robust to lhci output layout:
 *   1) prefer `<outputDir>/manifest.json` (written by `lhci upload --target=filesystem`) →
 *      use the representative (median) run per URL;
 *   2) else scan raw `lhr-*.json` left by `lhci collect` in `.lighthouseci/` (+ gate/) and compute
 *      the per-URL median for each metric.
 * Run from the `frontend/` cwd. Never throws — prints a diagnostic and exits 0.
 */
const fs = require("fs");
const path = require("path");

const ROOT = ".lighthouseci";
const GATE = path.join(ROOT, "gate");

function readJSON(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (_) {
    return null;
  }
}
function metricsOf(lhr) {
  const a = lhr.audits || {};
  const c = lhr.categories || {};
  const n = (k) => (a[k] && typeof a[k].numericValue === "number" ? a[k].numericValue : null);
  return {
    url: lhr.finalDisplayedUrl || lhr.finalUrl || lhr.requestedUrl || "(unknown url)",
    lcp: n("largest-contentful-paint"),
    tbt: n("total-blocking-time"),
    cls: n("cumulative-layout-shift"),
    seo: c.seo ? c.seo.score : null,
    a11y: c.accessibility ? c.accessibility.score : null,
  };
}
function fmt(m) {
  return (
    `${m.url}` +
    ` | LCP=${m.lcp != null ? Math.round(m.lcp) : "?"}ms` +
    ` | TBT=${m.tbt != null ? Math.round(m.tbt) : "?"}ms` +
    ` | CLS=${m.cls != null ? m.cls.toFixed(3) : "?"}` +
    ` | SEO=${m.seo != null ? m.seo : "?"}` +
    ` | A11Y=${m.a11y != null ? m.a11y : "?"}`
  );
}
function median(nums) {
  const x = nums.filter((v) => v != null).sort((a, b) => a - b);
  return x.length ? x[Math.floor((x.length - 1) / 2)] : null;
}

console.log("[LOCAL-BASELINE] === Phase 13.4 Plan 04 Task 2: LOCAL gate baseline (lhci-gate, median run) ===");
let printed = 0;
try {
  // (1) manifest path
  for (const dir of [GATE, ROOT]) {
    const mp = path.join(dir, "manifest.json");
    if (printed === 0 && fs.existsSync(mp)) {
      const manifest = readJSON(mp);
      if (Array.isArray(manifest)) {
        for (const r of manifest) {
          if (!r.isRepresentativeRun) continue;
          let lp = r.jsonPath;
          if (!lp || !fs.existsSync(lp)) lp = path.join(dir, path.basename(r.jsonPath || ""));
          const lhr = fs.existsSync(lp) ? readJSON(lp) : null;
          if (!lhr) continue;
          console.log("[LOCAL-BASELINE] " + fmt(metricsOf(lhr)));
          printed++;
        }
      }
    }
  }
  // (2) raw lhr-*.json fallback
  if (printed === 0) {
    console.log("[LOCAL-BASELINE] (no manifest — computing per-URL median from raw lhr-*.json)");
    const byUrl = {};
    for (const dir of [ROOT, GATE]) {
      if (!fs.existsSync(dir)) continue;
      for (const f of fs.readdirSync(dir)) {
        if (!/^lhr-.*\.json$/.test(f)) continue;
        const lhr = readJSON(path.join(dir, f));
        if (!lhr) continue;
        const m = metricsOf(lhr);
        (byUrl[m.url] = byUrl[m.url] || []).push(m);
      }
    }
    for (const url of Object.keys(byUrl).sort()) {
      const ms = byUrl[url];
      console.log(
        "[LOCAL-BASELINE] " +
          fmt({
            url,
            lcp: median(ms.map((m) => m.lcp)),
            tbt: median(ms.map((m) => m.tbt)),
            cls: median(ms.map((m) => m.cls)),
            seo: median(ms.map((m) => m.seo)),
            a11y: median(ms.map((m) => m.a11y)),
          }) +
          ` (median of ${ms.length} runs)`
      );
      printed++;
    }
  }
  if (printed === 0) {
    console.log(`[LOCAL-BASELINE] no lhr data found in ${ROOT}/ or ${GATE}/ — did 'lhci collect' run?`);
  }
} catch (err) {
  console.log(`[LOCAL-BASELINE] error: ${err && err.message ? err.message : err}`);
}
console.log("[LOCAL-BASELINE] === end (copy these into tests/seo_proof.md SC5 LOCAL baseline) ===");
process.exit(0);
