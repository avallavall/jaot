import { test, expect, request, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Post-solve analysis page E2E (v3.1 Workstream A). Solves a JModel through the studio,
 * follows the results drawer's "View full results" CTA (A5) to the execution-detail page,
 * and asserts the analysis surfaces the v3.1 overhaul introduced:
 *   - A1 structured (grouped-by-family) solution view;
 *   - A2 honest solve fact-card (root node / N nodes / time-limit) instead of a fake chart;
 *   - A3 exact, solution-based analysis (binding / contributions), loaded on demand;
 *   - A4 variable-values chart collapsed to an aggregate for a binary-dominant solution.
 *
 * Needs JAOT_DSL ON (to author + solve a JModel that carries index structure). The flag is
 * driven via a throwaway admin API context and restored in afterAll so it never leaks.
 */

const NAV = 20_000;
const SOLVE = 40_000;
const BASE = process.env.BASE_URL || "http://localhost:3000";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || "admin@jaot.io";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "AdminPass123!";

// A binary family x_{1..20}, capacity 12: the solution sets 12 of them to 1 (identical
// bars) and 8 to 0. This gives (a) index structure for the grouped view (family "x"), and
// (b) enough identical nonzero bars (>=3, all equal) to trigger A4's aggregate collapse.
// The indexed `lim` family (20 rows, exactly 12 binding regardless of WHICH 12 the solver
// picks) drives the Sensitivity L1 family-KPI table; scalar `cap` stays family-less.
const VALID_JMODEL = `set I := 1..20;
var x{I} binary;
maximize obj: sum{i in I} x[i];
subject to cap: sum{i in I} x[i] <= 12;
subject to lim{i in I}: x[i] <= 1;`;

async function setDslFlag(value: "true" | "false"): Promise<void> {
  const ctx = await request.newContext({ baseURL: BASE });
  try {
    const login = await ctx.post("/api/v2/auth/login/email", {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(login.ok(), `admin login failed: ${login.status()}`).toBeTruthy();
    const resp = await ctx.put("/api/v2/admin/settings/values", {
      data: { updates: { JAOT_DSL: value } },
    });
    expect(resp.ok(), `set JAOT_DSL=${value} failed: ${resp.status()}`).toBeTruthy();
  } finally {
    await ctx.dispose();
  }
}

async function readDslFlag(): Promise<"true" | "false"> {
  const ctx = await request.newContext({ baseURL: BASE });
  try {
    const login = await ctx.post("/api/v2/auth/login/email", {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(login.ok(), `admin login failed: ${login.status()}`).toBeTruthy();
    const resp = await ctx.get("/api/v2/dsl/status");
    expect(resp.ok(), `read JAOT_DSL failed: ${resp.status()}`).toBeTruthy();
    return (await resp.json()).enabled ? "true" : "false";
  } finally {
    await ctx.dispose();
  }
}

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

test.describe("Studio — post-solve analysis page (v3.1 A1-A5, gated by JAOT_DSL)", () => {
  let priorDslFlag: "true" | "false" = "false";

  test.beforeAll(async () => {
    priorDslFlag = await readDslFlag();
  });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "jaot_cookie_consent",
        JSON.stringify({ essential: true, analytics: false, timestamp: "2026-06-26T00:00:00.000Z" }),
      );
    });
  });

  test.afterAll(async () => {
    await setDslFlag(priorDslFlag);
  });

  test("solve a JModel → drawer CTA → structured view + honest fact-card + exact analysis", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    // Author + compile the model.
    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    // Solve it through the studio Solve tab.
    await page.getByTestId("studio-tab-solve").click();
    const runBtn = page.getByTestId("studio-solve-run");
    await expect(runBtn).toBeEnabled({ timeout: NAV });
    await runBtn.click();
    // "View results" appears when the solve is done; it opens the results drawer.
    const doneBtn = page.getByTestId("studio-solve-done");
    await expect(doneBtn).toBeVisible({ timeout: SOLVE });

    // A6b: the ambient "solving…" pill clears once the solve completes (no lingering).
    await expect(page.getByTestId("studio-solving-indicator")).toHaveCount(0, { timeout: NAV });

    // A5: the studio drawer is a summary + a "View full results" CTA (not a wall of rows).
    await doneBtn.click();
    const viewFull = page.getByTestId("drawer-view-full-results");
    await expect(viewFull).toBeVisible({ timeout: NAV });
    await viewFull.click();

    // Land on the execution-detail page.
    await page.waitForURL(/\/solve\/executions\/exe_[A-Za-z0-9]+/, { timeout: NAV });

    // The Results tab (default) leads with the v3.1 analysis surfaces:
    // A1: the grouped, structured solution view (family x → its indices).
    await expect(page.getByTestId("structured-view-grouped")).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("structured-groups")).toBeVisible({ timeout: NAV });

    // A2: an honest fact-card (root node / N nodes / time-limit), not a flat convergence chart.
    await expect(page.getByTestId("solve-fact-card")).toBeVisible({ timeout: NAV });

    // A3: exact, solution-based analysis auto-loads and leads with binding/contribution facts.
    await expect(page.getByTestId("exact-analysis")).toBeVisible({ timeout: SOLVE });

    // Sensitivity L1: the family KPI table aggregates the indexed `lim` family — 12 of its
    // 20 rows are binding no matter which 12 items the solver picked — while the scalar
    // `cap` row carries no family and stays out of the table.
    const familyTable = page.getByTestId("exact-analysis-families");
    await expect(familyTable).toBeVisible({ timeout: NAV });
    await expect(familyTable).toContainText("lim");
    await expect(familyTable).toContainText("12/20");
    await expect(familyTable).not.toContainText("cap");
    // ...and the objective contributions roll up by variable family (all 20 x-terms → 12).
    const familyBars = page.getByTestId("exact-analysis-family-contributions");
    await expect(familyBars).toBeVisible({ timeout: NAV });
    await expect(familyBars).toContainText("x");

    // A4: on the Visualization tab, a binary-dominant solution collapses the identical-bars
    // chart to an aggregate ("N at 1.0 / M at 0") instead of a wall of equal bars.
    await page.getByTestId("execution-tab-visualization").click();
    await expect(page.getByTestId("variable-values-aggregate")).toBeVisible({ timeout: NAV });
  });
});
