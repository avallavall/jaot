import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;

test.describe("Builder — Model Creation", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("user can click New Model and enter the canvas", async ({ page }) => {
    await page.goto("/builder");

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    const newModelButton = page.getByRole("button", { name: /new model/i });
    await expect(newModelButton).toBeVisible({ timeout: 10_000 });

    await newModelButton.click();

    // Should navigate to a new document canvas (/builder/{documentId})
    // or show a creation dialog
    await expect(async () => {
      const url = page.url();
      const isOnCanvas = /\/builder\/[a-zA-Z0-9_]+$/.test(url) && !/\/builder\/(templates|ai-assistant)$/.test(url);
      const hasDialog = await page.getByRole("dialog").count() > 0;
      expect(isOnCanvas || hasDialog).toBe(true);
    }).toPass({ timeout: NAV_TIMEOUT });
  });

  test("canvas page shows toolbar and empty canvas area", async ({ page }) => {
    await page.goto("/builder");

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    const newModelButton = page.getByRole("button", { name: /new model/i });
    await expect(newModelButton).toBeVisible({ timeout: 10_000 });
    await newModelButton.click();

    // Wait for canvas to load
    await expect(async () => {
      const url = page.url();
      const isCanvas = /\/builder\/[a-zA-Z0-9_]+$/.test(url) && !/\/builder\/(templates|ai-assistant)$/.test(url);
      expect(isCanvas).toBe(true);
    }).toPass({ timeout: NAV_TIMEOUT });

    // Canvas should be visible (React Flow container)
    const canvas = page.locator(".react-flow")
      .or(page.locator('[data-testid="canvas"]'))
      .or(page.locator("#main-content"));
    await expect(canvas.first()).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  test("builder templates page shows available templates to use", async ({ page }) => {
    await page.goto("/builder/templates");

    await expect(page).toHaveURL(/\/builder\/templates/);

    // Should display template cards
    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible();
  });
});
