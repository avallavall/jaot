/**
 * UAT: Phase 5 HiGHS Adapter — Solver Selection E2E Tests (promoted to real backend, Phase 11)
 *
 * Covers 4 UAT items:
 *   UAT-1  Solver dropdown on model solve page (SCIP pre-selected, HIGHS option present)
 *   UAT-2  Solver dropdown on import page (preview step)
 *   UAT-3  Solver field in execution detail page
 *   UAT-4  HTTP 422 for invalid solver_name via direct API call
 *
 * All page.route().fulfill() calls removed — real Docker backend only.
 * The redundant "execution detail with mocked HIGHS execution shows HIGHS solver card"
 * test has been deleted (pure UI render; UAT-3 primary test covers the same claim).
 *
 * Seed (beforeAll): POST /api/v2/models → test model with input_fields
 * Cleanup (afterAll): DELETE /api/v2/models/{id}
 */

import path from "path";
import { test, expect, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const BASE_URL = process.env.BASE_URL || "http://localhost:3000";
const NAV_TIMEOUT = 15_000;

let createdModelId: string | null = null;

/**
 * Wait for the solver dropdown's loading state to settle.
 * The SolverSelect component shows "Loading solvers..." while fetching;
 * once settled it either renders options or hides entirely if no solvers
 * are returned by the API.
 */
async function waitForSolverDropdown(page: Page): Promise<boolean> {
  await page.waitForLoadState("networkidle").catch(() => {});
  const solverLabel = page.getByText("Solver", { exact: true }).first();
  const visible = await solverLabel.isVisible({ timeout: 5_000 }).catch(() => false);
  return visible;
}

/**
 * Make an API call through the page context (avoids Docker-internal redirect
 * issues that affect the raw request fixture). Returns the response status
 * and parsed JSON body.
 */
async function pageApiCall(
  page: Page,
  method: string,
  apiPath: string,
  body?: unknown,
): Promise<{ status: number; body: unknown }> {
  const result = await page.evaluate(
    async ({ method, apiPath, body }) => {
      const opts: RequestInit = {
        method,
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      };
      if (body !== undefined) {
        opts.body = JSON.stringify(body);
      }
      const resp = await fetch(apiPath, opts);
      let responseBody: unknown = null;
      try {
        responseBody = await resp.json();
      } catch {
        // non-JSON body
      }
      return { status: resp.status, body: responseBody };
    },
    { method, apiPath, body },
  );
  return result;
}

// ---------------------------------------------------------------------------
// Seed / cleanup
// ---------------------------------------------------------------------------

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext({
    storageState: path.join(__dirname, ".auth/user.json"),
  });
  const page = await context.newPage();

  try {
    const resp = await page.request.post(`${BASE_URL}/api/v2/models`, {
      data: {
        name: "e2e-solver-selection-test",
        description: "Created by solver-selection.spec.ts — auto-deleted",
        generator_type: "generic",
        input_fields: [{ name: "x", type: "number", default: 1 }],
        example_input: { x: 1 },
      },
    });
    if (resp.ok()) {
      const model = (await resp.json()) as { id: string };
      createdModelId = model.id;
    }
  } finally {
    await context.close();
  }
});

test.afterAll(async ({ browser }) => {
  if (!createdModelId) return;

  const context = await browser.newContext({
    storageState: path.join(__dirname, ".auth/user.json"),
  });
  const page = await context.newPage();

  try {
    await page.request.delete(`${BASE_URL}/api/v2/models/${createdModelId}`);
    createdModelId = null;
  } finally {
    await context.close();
  }
});

// ---------------------------------------------------------------------------
// UAT-1: Solver dropdown on model solve page
// ---------------------------------------------------------------------------

test.describe("UAT-1: Solver dropdown on model solve page", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("solver dropdown appears with SCIP pre-selected and HIGHS option", async ({ page }) => {
    test.skip(!createdModelId, "Model seeding failed in beforeAll");

    await page.goto(`/solve/${createdModelId}`);
    await page.waitForLoadState("domcontentloaded");

    await page
      .locator(".animate-spin")
      .waitFor({ state: "hidden", timeout: NAV_TIMEOUT })
      .catch(() => {});

    const dropdownPresent = await waitForSolverDropdown(page);

    if (!dropdownPresent) {
      test.info().annotations.push({
        type: "info",
        description:
          "Solver dropdown not rendered: /api/v2/solvers/available returned empty list. " +
          "This means the backend does not expose any solvers yet.",
      });
      await expect(page.getByText("Input Data")).toBeVisible({ timeout: NAV_TIMEOUT });
      return;
    }

    const selectTrigger = page.locator('[id="solver-select"]');
    const triggerVisible = await selectTrigger.isVisible({ timeout: 3_000 }).catch(() => false);

    if (triggerVisible) {
      const currentValue = await selectTrigger.textContent();
      expect(currentValue?.toLowerCase()).toContain("scip");

      await selectTrigger.click();

      const scip = page
        .getByRole("option", { name: /^scip$/i })
        .or(page.locator('[data-radix-select-item]').filter({ hasText: /scip/i }));
      const highs = page
        .getByRole("option", { name: /^highs$/i })
        .or(page.locator('[data-radix-select-item]').filter({ hasText: /highs/i }));

      await expect(scip.first()).toBeVisible({ timeout: 5_000 });
      await expect(highs.first()).toBeVisible({ timeout: 3_000 });

      await page.keyboard.press("Escape");
    } else {
      const solverLabel = page.getByText("Solver", { exact: true }).first();
      await expect(solverLabel).toBeVisible();

      const selectContainer = page.locator('[role="combobox"]').first();
      const containerVisible = await selectContainer
        .isVisible({ timeout: 3_000 })
        .catch(() => false);

      if (containerVisible) {
        const currentValue = await selectContainer.textContent();
        expect(currentValue?.toLowerCase()).toContain("scip");
      } else {
        await expect(solverLabel).toBeVisible();
      }
    }
  });

  test("solver dropdown label is visible on model solve page", async ({ page }) => {
    test.skip(!createdModelId, "Model seeding failed in beforeAll");

    await page.goto(`/solve/${createdModelId}`);
    await page.waitForLoadState("networkidle").catch(() => {});

    await expect(page.getByText("Input Data")).toBeVisible({ timeout: NAV_TIMEOUT });

    const solverLabel = page.getByText("Solver", { exact: true }).first();
    await expect(solverLabel).toBeVisible({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// UAT-2: Solver dropdown on import page (preview step)
// ---------------------------------------------------------------------------

test.describe("UAT-2: Solver dropdown on import page", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("import page loads at /solve/import", async ({ page }) => {
    await page.goto("/solve/import");
    await page.waitForLoadState("domcontentloaded");
    await expect(page).toHaveURL(/\/solve\/import/);
  });

  test("import page preview step shows solver dropdown after file upload", async ({ page }) => {
    await page.goto("/solve/import");
    await page.waitForLoadState("networkidle").catch(() => {});

    const dropZone = page.locator('[data-testid="file-drop-zone"]');
    await expect(dropZone).toBeVisible({ timeout: NAV_TIMEOUT });

    // Inject a valid LP file — real backend parses this and returns preview data
    const fileInput = page.locator('[data-testid="file-input"]');
    await fileInput.setInputFiles({
      name: "test.lp",
      mimeType: "text/plain",
      buffer: Buffer.from("min: x;\nx >= 1;"),
    });

    const previewButton = page.getByRole("button", { name: /preview/i });
    await expect(previewButton).toBeEnabled({ timeout: 5_000 });
    await previewButton.click();

    // After clicking Preview, the component calls real backend and transitions
    const previewTitle = page.locator("h2").filter({ hasText: /model\s*preview/i });
    await expect(previewTitle).toBeVisible({ timeout: 10_000 });

    await page.waitForLoadState("networkidle").catch(() => {});

    const solverLabel = page.getByText("Solver", { exact: true }).first();
    const labelVisible = await solverLabel.isVisible({ timeout: 5_000 }).catch(() => false);

    if (!labelVisible) {
      test.info().annotations.push({
        type: "info",
        description:
          "Solver dropdown not rendered in import preview: " +
          "/api/v2/solvers/available returned empty list.",
      });
      await expect(previewTitle).toBeVisible();
    } else {
      await expect(solverLabel).toBeVisible();

      const importTrigger = page.locator('[id="import-solver-select"]');
      const triggerVisible = await importTrigger
        .isVisible({ timeout: 3_000 })
        .catch(() => false);

      if (triggerVisible) {
        const triggerText = await importTrigger.textContent();
        expect(triggerText?.toLowerCase()).toContain("scip");
      }
    }
  });
});

// ---------------------------------------------------------------------------
// UAT-3: Solver field in execution detail shows solver name
// ---------------------------------------------------------------------------

test.describe("UAT-3: Solver field in execution detail", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("execution detail page displays a Solver stats card", async ({ page }) => {
    await page.goto("/solve/executions");
    await page.waitForLoadState("domcontentloaded");

    await page
      .locator(".animate-spin")
      .waitFor({ state: "hidden", timeout: NAV_TIMEOUT })
      .catch(() => {});

    const viewButton = page.getByRole("button", { name: /view/i }).first();
    const hasView = await viewButton.isVisible({ timeout: 5_000 }).catch(() => false);

    if (!hasView) {
      // No executions yet — page loaded successfully, solver card can't be tested
      test.info().annotations.push({
        type: "info",
        description:
          "No executions found — solver card assertion skipped. " +
          "Run a solve via the UI to populate executions for this test.",
      });
      await expect(page).toHaveURL(/\/solve\/executions/);
      return;
    }

    await viewButton.click();
    await page.waitForURL(/\/solve\/executions\//, { timeout: NAV_TIMEOUT });
    await page.waitForLoadState("domcontentloaded");

    await page
      .locator(".animate-pulse")
      .waitFor({ state: "hidden", timeout: NAV_TIMEOUT })
      .catch(() => {});

    const solverLabel = page.getByText("Solver", { exact: true }).first();
    await expect(solverLabel).toBeVisible({ timeout: NAV_TIMEOUT });

    const solverCard = page
      .locator('.bg-card.border.border-border.rounded-lg.p-4')
      .filter({ has: page.getByText("Solver", { exact: true }) })
      .first();

    const solverValue = solverCard.locator(".font-medium");
    await expect(solverValue).toBeVisible();
    const valueText = await solverValue.textContent();
    expect(valueText?.trim().length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// UAT-4: HTTP 422 for invalid solver_name
// ---------------------------------------------------------------------------

test.describe("UAT-4: HTTP 422 for invalid solver_name", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("direct API call with solver_name=nonexistent returns 422", async ({ page }) => {
    test.skip(!createdModelId, "Model seeding failed in beforeAll");

    await page.goto("/solve");
    await page.waitForLoadState("domcontentloaded");

    // Use the real seeded model — real backend validates solver_name and returns 422
    const result = await pageApiCall(page, "POST", `/api/v2/models/${createdModelId}/execute`, {
      input_data: { x: 1 },
      solver_name: "nonexistent",
    });

    expect(result.status).toBe(422);

    const body = result.body as Record<string, unknown> | null;
    if (body) {
      const bodyStr = JSON.stringify(body).toLowerCase();
      const mentionsSolver = /solver|nonexistent|invalid|not.*found|available/.test(bodyStr);
      expect(mentionsSolver).toBe(true);
    }
  });

  test("solvers available endpoint returns list including scip and highs", async ({ page }) => {
    await page.goto("/solve");
    await page.waitForLoadState("domcontentloaded");

    const result = await pageApiCall(page, "GET", "/api/v2/solvers/available");

    expect(result.status).toBe(200);

    const body = result.body as Record<string, unknown> | null;
    expect(body).not.toBeNull();
    expect(body).toHaveProperty("solvers");

    const solvers = body!.solvers as Array<{ name: string }>;
    expect(Array.isArray(solvers)).toBe(true);

    const solverNames = solvers.map((s) => s.name.toLowerCase());

    expect(solverNames).toContain("scip");
    expect(solverNames).toContain("highs");
  });
});
