// Review utility: full-page screenshots of the home in light/dark, desktop/mobile.
// reducedMotion:"reduce" forces all <Reveal> content visible (via the
// [data-reveal] override in globals.css) so off-screen sections aren't captured
// mid-fade. Output dir is configurable via SHOT_OUT.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const BASE = process.env.SHOT_BASE_URL || "http://localhost:3001";
const OUT = process.env.SHOT_OUT || path.resolve("home-review");

const combos = [
  { name: "desktop-light", w: 1440, h: 900, theme: "light", dsf: 1.5 },
  { name: "desktop-dark", w: 1440, h: 900, theme: "dark", dsf: 1.5 },
  { name: "mobile-light", w: 390, h: 844, theme: "light", dsf: 2 },
  { name: "mobile-dark", w: 390, h: 844, theme: "dark", dsf: 2 },
];

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();

for (const c of combos) {
  const ctx = await browser.newContext({
    viewport: { width: c.w, height: c.h },
    deviceScaleFactor: c.dsf,
    reducedMotion: "reduce",
  });
  await ctx.addInitScript(
    ([ck, th]) => {
      try {
        localStorage.setItem(
          ck,
          JSON.stringify({
            essential: true,
            analytics: true,
            timestamp: new Date().toISOString(),
          }),
        );
        localStorage.setItem("jaot_theme", th);
      } catch {
        /* ignore */
      }
    },
    ["jaot_cookie_consent", c.theme],
  );
  const page = await ctx.newPage();
  await page.goto(`${BASE}/en`, { waitUntil: "load" });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1500); // fonts + hero image
  await page.screenshot({
    path: path.join(OUT, `home-${c.name}.png`),
    fullPage: true,
  });
  await ctx.close();
  console.log("saved", c.name);
}

await browser.close();
console.log("DONE " + OUT);
