import { test, expect, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Marketing screenshot capture for the v3.1 analysis workbench — NOT a test.
 *
 * Solves a small assignment JModel and captures the execution page's analysis
 * surface (structured solution + solve summary + exact analysis) in light and
 * dark themes, writing the /showcase images the home page embeds.
 *
 * Skipped unless CAPTURE_SHOTS=1 so the regular E2E sweep never runs it:
 *   CAPTURE_SHOTS=1 npx playwright test e2e/v31-showcase-shots.spec.ts --project=chromium
 */

const NAV = 20_000;
const SOLVE = 40_000;

// The docs' 3x3 assignment: 2-index binary family (grouped view shows per-worker
// choices), equality constraints (all binding in the exact analysis), and varied
// cost contributions — a representative, compact analysis page.
const ASSIGNMENT_JMODEL = `set WORKERS := {Ana, Bo, Cai};
set TASKS := {cutting, packing, quality};

param cost{WORKERS, TASKS} :=
    Ana cutting 9, Ana packing 2, Ana quality 7,
    Bo cutting 6, Bo packing 4, Bo quality 3,
    Cai cutting 5, Cai packing 8, Cai quality 1;

var assign{WORKERS, TASKS} binary;

minimize total_cost:
    sum{w in WORKERS, t in TASKS} cost[w, t] * assign[w, t];

subject to one_worker_per_task{t in TASKS}:
    sum{w in WORKERS} assign[w, t] == 1;

subject to one_task_per_worker{w in WORKERS}:
    sum{t in TASKS} assign[w, t] == 1;`;

async function createBlankProject(page: Page): Promise<string> {
  await page.goto("/studio/new");
  const blank = page.getByTestId("launcher-tile-blank");
  await expect(blank).toBeVisible({ timeout: NAV });
  await blank.click();
  await page.waitForURL(/\/studio\/(mp_[A-Za-z0-9]+)\/build/, { timeout: NAV });
  const match = page.url().match(/\/studio\/(mp_[A-Za-z0-9]+)\//);
  if (!match) throw new Error(`No project id in URL: ${page.url()}`);
  return match[1];
}

/** Clip spanning the structured solution through the exact analysis, in page coords.
 *  The viewport is tall enough that the whole region sits inside it at scrollY=0. */
async function analysisClip(page: Page) {
  await page.evaluate(() => window.scrollTo(0, 0));
  return page.evaluate(() => {
    const top = document.querySelector('[data-testid="structured-view-grouped"]');
    const bottom = document.querySelector('[data-testid="exact-analysis"]');
    if (!top || !bottom) throw new Error("analysis anchors missing");
    const a = top.getBoundingClientRect();
    const b = bottom.getBoundingClientRect();
    const x = Math.max(0, Math.min(a.left, b.left) - 16);
    const y = Math.max(0, a.top - 56); // include the section heading
    const width = Math.max(a.right, b.right) - x + 16;
    const height = b.bottom + 16 - y;
    return { x, y, width, height };
  });
}

test.describe("v3.1 showcase screenshots (explicit capture only)", () => {
  test.skip(!process.env.CAPTURE_SHOTS, "capture run — set CAPTURE_SHOTS=1 to record");

  test.use({ viewport: { width: 1240, height: 2600 }, deviceScaleFactor: 2 });




  test("capture the analysis page in light and dark", async ({ page }) => {
    await interceptGuidanceApi(page);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "jaot_cookie_consent",
        JSON.stringify({ essential: true, analytics: false, timestamp: "2026-06-26T00:00:00.000Z" }),
      );
    });

    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);
    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    await textarea.fill(ASSIGNMENT_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    await page.getByTestId("studio-tab-solve").click();
    const runBtn = page.getByTestId("studio-solve-run");
    await expect(runBtn).toBeEnabled({ timeout: NAV });
    await runBtn.click();
    const doneBtn = page.getByTestId("studio-solve-done");
    await expect(doneBtn).toBeVisible({ timeout: SOLVE });
    await doneBtn.click();
    const viewFull = page.getByTestId("drawer-view-full-results");
    await expect(viewFull).toBeVisible({ timeout: NAV });
    await viewFull.click();
    await page.waitForURL(/\/solve\/executions\/exe_[A-Za-z0-9]+/, { timeout: NAV });

    // Light.
    await expect(page.getByTestId("exact-analysis")).toBeVisible({ timeout: SOLVE });
    await page.screenshot({
      path: "public/showcase/v31-analysis-light.png",
      clip: await analysisClip(page),
    });

    // Dark: flip the next-themes storage key and reload (the page refetches).
    await page.evaluate(() => window.localStorage.setItem("jaot_theme", "dark"));
    await page.reload();
    await expect(page.getByTestId("exact-analysis")).toBeVisible({ timeout: SOLVE });
    await page.screenshot({
      path: "public/showcase/v31-analysis-dark.png",
      clip: await analysisClip(page),
    });
  });
});
