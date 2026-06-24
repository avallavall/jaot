import path from "path";
import { test, expect } from "@playwright/test";
import { TriggersPage } from "./pages/triggers.page";

/**
 * Cron Scheduling E2E Tests (Phase 67-03 → promoted to real backend, Phase 11).
 *
 * Tests the trigger detail page schedule tab and run history tab against the
 * real Docker backend — no page.route().fulfill() calls.
 *
 * Seed chain (beforeAll):
 *   POST /api/v2/builder/                          → builder document
 *   POST /api/v2/builder/{doc_id}/versions/        → version checkpoint
 *   POST /api/v2/triggers                          → trigger (uses doc_id + version_id)
 *
 * Cleanup chain (afterAll):
 *   DELETE /api/v2/triggers/{trigger_id}
 *   DELETE /api/v2/builder/{doc_id}               → cascades version
 *
 * Auth: chromium project storageState (user.json from global.setup.ts).
 * Run history: new trigger has 0 runs — tests assert empty state (no seeding endpoint).
 */

const BASE_URL = process.env.BASE_URL || "http://localhost:3000";

let createdTriggerId: string | null = null;
let createdDocumentId: string | null = null;

/** Wait for Next.js hydration */
async function waitForHydration(page: import("@playwright/test").Page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForLoadState("domcontentloaded");
}

test.describe("Cron Scheduling E2E", () => {
  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: path.join(__dirname, ".auth/user.json"),
    });
    const page = await context.newPage();

    try {
      // Step 1: Create a builder document
      const docResp = await page.request.post(`${BASE_URL}/api/v2/builder/`, {
        data: { name: "e2e-cron-test-doc" },
      });
      if (!docResp.ok()) {
        await context.close();
        return;
      }
      const doc = (await docResp.json()) as { id: string };
      createdDocumentId = doc.id;

      // Step 2: Create a version checkpoint
      const versionResp = await page.request.post(
        `${BASE_URL}/api/v2/builder/${createdDocumentId}/versions/`,
        { data: { canvas_json: {} } },
      );
      if (!versionResp.ok()) {
        await context.close();
        return;
      }
      const version = (await versionResp.json()) as { id: string };

      // Step 3: Create a trigger
      const triggerResp = await page.request.post(`${BASE_URL}/api/v2/triggers`, {
        data: {
          name: "e2e-cron-schedule-test",
          description: "Created by cron.spec.ts — auto-deleted",
          document_id: createdDocumentId,
          version_id: version.id,
          webhook_url: "https://example.com/e2e-webhook",
        },
      });
      if (!triggerResp.ok()) {
        await context.close();
        return;
      }
      const trigger = (await triggerResp.json()) as { id: string };
      createdTriggerId = trigger.id;
    } finally {
      await context.close();
    }
  });

  test.afterAll(async ({ browser }) => {
    if (!createdTriggerId && !createdDocumentId) return;

    const context = await browser.newContext({
      storageState: path.join(__dirname, ".auth/user.json"),
    });
    const page = await context.newPage();

    try {
      if (createdTriggerId) {
        await page.request.delete(`${BASE_URL}/api/v2/triggers/${createdTriggerId}`);
        createdTriggerId = null;
      }
      if (createdDocumentId) {
        await page.request.delete(`${BASE_URL}/api/v2/builder/${createdDocumentId}`);
        createdDocumentId = null;
      }
    } finally {
      await context.close();
    }
  });

  test("displays schedule tab and shows empty schedule state", async ({ page }) => {
    test.skip(!createdTriggerId, "Trigger seeding failed in beforeAll");

    const triggers = new TriggersPage(page);
    await triggers.goto(createdTriggerId!);
    await waitForHydration(page);

    await triggers.openScheduleTab();

    // A freshly-created trigger has no schedule — real backend returns 404 on GET schedule
    await expect(triggers.setupScheduleButton).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/no schedule configured/i)).toBeVisible({ timeout: 10_000 });
  });

  test("shows empty state when no schedule exists", async ({ page }) => {
    test.skip(!createdTriggerId, "Trigger seeding failed in beforeAll");

    const triggers = new TriggersPage(page);
    await triggers.goto(createdTriggerId!);
    await waitForHydration(page);

    await triggers.openScheduleTab();

    await expect(triggers.setupScheduleButton).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/no schedule configured/i)).toBeVisible({ timeout: 10_000 });
  });

  test("creates a new schedule with day and time selection", async ({ page }) => {
    test.skip(!createdTriggerId, "Trigger seeding failed in beforeAll");

    const triggers = new TriggersPage(page);
    await triggers.goto(createdTriggerId!);
    await waitForHydration(page);

    await triggers.openScheduleTab();

    // Click "Set up schedule" to show the form
    await triggers.setupScheduleButton.click();

    // Wait for the schedule form to appear
    await expect(triggers.saveButton).toBeVisible({ timeout: 10_000 });

    // Select days using the DayOfWeekPicker
    const monButton = page.locator("button[aria-pressed]").filter({ hasText: /Mon/i });
    const wedButton = page.locator("button[aria-pressed]").filter({ hasText: /Wed/i });
    const friButton = page.locator("button[aria-pressed]").filter({ hasText: /Fri/i });

    await monButton.click();
    await wedButton.click();
    await friButton.click();

    // Interact with hour select (Radix Select component)
    const hourTrigger = page.getByRole("combobox").first();
    await hourTrigger.click();

    const hourOption = page.getByRole("option", { name: "10:00" });
    await hourOption.waitFor({ state: "visible", timeout: 5_000 }).catch(() => {});
    if (await hourOption.isVisible()) {
      await hourOption.click();
    } else {
      await page.keyboard.press("Escape");
    }

    // Click Save — real backend validates cron expression and creates the schedule
    await triggers.saveButton.click();

    // After save, backend created the schedule — UI transitions to enabled view
    await expect(page.getByText(/schedule enabled/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("toggles schedule enable/disable", async ({ page }) => {
    test.skip(!createdTriggerId, "Trigger seeding failed in beforeAll");

    const triggers = new TriggersPage(page);
    await triggers.goto(createdTriggerId!);
    await waitForHydration(page);

    await triggers.openScheduleTab();

    // The trigger may or may not have a schedule from a prior test run.
    // Ensure a schedule exists before testing the toggle.
    const hasSetupButton = await triggers.setupScheduleButton
      .isVisible({ timeout: 3_000 })
      .catch(() => false);

    if (hasSetupButton) {
      await triggers.setupScheduleButton.click();
      await expect(triggers.saveButton).toBeVisible({ timeout: 10_000 });
      await triggers.saveButton.click();
      await expect(page.getByText(/schedule enabled/i).first()).toBeVisible({ timeout: 10_000 });
    }

    // Verify schedule is enabled
    await expect(page.getByText(/schedule enabled/i).first()).toBeVisible({ timeout: 10_000 });

    // Click "Disable schedule" — real backend PATCH disables it
    await triggers.disableToggle.click();

    await expect(page.getByText(/schedule paused/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("shows empty run history when trigger has no runs", async ({ page }) => {
    test.skip(!createdTriggerId, "Trigger seeding failed in beforeAll");

    const triggers = new TriggersPage(page);
    await triggers.goto(createdTriggerId!);
    await waitForHydration(page);

    await triggers.openRunHistoryTab();

    // A freshly-created trigger has 0 runs — real backend returns empty list
    await expect(page.getByText(/no runs yet/i)).toBeVisible({ timeout: 10_000 });
  });
});
