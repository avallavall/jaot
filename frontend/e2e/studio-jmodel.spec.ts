import { test, expect, request, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Studio JModel (DSL) lens E2E (P5). The feature ships DARK behind the JAOT_DSL
 * platform flag, so this spec drives the flag itself via a throwaway admin API
 * context (the regular `page` session is a non-admin user), then asserts:
 *   - gating: flag OFF → the JModel sub-lens is hidden and ?lens=jmodel falls back;
 *   - flow: flag ON → a valid source compiles, a broken source blocks solve, and a
 *     valid model solves through the Solve tab.
 * The flag is restored to OFF in afterAll so it never leaks into other specs.
 */

const NAV = 20_000;
const BASE = process.env.BASE_URL || "http://localhost:3000";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || "admin@jaot.io";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "AdminPass123!";

// pick 2 of {a:2, b:3, c:4} to maximize → c + b = 7.
const VALID_JMODEL = `set I := {a, b, c};
param w{I} := a 2, b 3, c 4;
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to pick_two: sum{i in I} x[i] <= 2;`;

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

/** Read the current JAOT_DSL flag so afterAll can restore it (the owner may run local
 *  with it ON to test — this spec must not silently turn it off for them). */
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

test.describe("Studio — JModel DSL lens (P5, gated by JAOT_DSL)", () => {
  let priorDslFlag: "true" | "false" = "false";

  test.beforeAll(async () => {
    priorDslFlag = await readDslFlag();
  });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test.afterAll(async () => {
    // Restore whatever the flag was before the suite ran (do not clobber the owner's ON).
    await setDslFlag(priorDslFlag);
  });

  test("gating: flag OFF hides the lens and ?lens=jmodel falls back to canvas", async ({
    page,
  }) => {
    await setDslFlag("false");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    // The workspace renders (canvas sub-lens present)...
    await expect(page.getByTestId("studio-sublens-canvas")).toBeVisible({ timeout: NAV });
    // ...but the JModel tab is not offered and the deep-link shows no JModel editor.
    await expect(page.getByTestId("studio-sublens-jmodel")).toHaveCount(0);
    await expect(page.getByTestId("studio-jmodel-textarea")).toHaveCount(0);
  });

  test("flag ON: valid source compiles, broken blocks solve, valid model solves", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    const headerSolve = page.getByTestId("studio-header-solve");

    // Valid JModel → compiles (no error) and solve is enabled.
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(headerSolve).toBeEnabled({ timeout: NAV });

    // Broken source → inline error and solve blocked.
    await textarea.fill("set I := {a, b}\nvar x{I} binary;");
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    // Fixing it clears the block, and the compiled model solves on the Solve tab.
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(headerSolve).toBeEnabled({ timeout: NAV });

    // Wait until the compiled model is autosaved (as a user does — they see "Saved"
    // before moving on). The compile is async and the draft autosaves 800ms after it;
    // switching tabs before that would race the persist. This is the ONE realistic wait
    // that keeps the client-side tab nav deterministic (a human never switches in the
    // ~600ms window the test otherwise hit).
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    // Client-side tab nav (NOT a reload) so the in-memory compiled model survives.
    await page.getByTestId("studio-tab-solve").click();
    const runBtn = page.getByTestId("studio-solve-run");
    await expect(runBtn).toBeEnabled({ timeout: NAV });
    await runBtn.click();
    await expect(page.getByTestId("studio-solve-done")).toBeVisible({ timeout: 40_000 });
    // (The compiled model's optimum = 7 is asserted by the compiler unit tests, which
    // solve it through the real SCIPAdapter; here we prove the studio path solves.)
  });
});
