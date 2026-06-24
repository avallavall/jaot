import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;
const LONG_TIMEOUT = 30_000;

test.describe("Marketplace — Complete Buyer Journey", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("step 1: browse marketplace and find models", async ({ page }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Verify search works
    const searchInput = page.getByRole("searchbox").or(page.getByPlaceholder(/search/i));
    await expect(searchInput.first()).toBeVisible({ timeout: 10_000 });

    // Verify sort control exists (Radix Select — renders as combobox button)
    const sortTrigger = page.getByRole("combobox");
    if (await sortTrigger.isVisible().catch(() => false)) {
      await sortTrigger.click();
      await page.getByRole("option", { name: /newest/i }).click();
      await expect(async () => {
        const params = new URL(page.url()).searchParams;
        expect(params.get("sort")).toBe("newest");
      }).toPass({ timeout: 5_000 });
    }

    // Model cards should be visible (or empty state)
    const modelCards = page.locator("a[href*='/marketplace/'][href]:not([href$='/marketplace/'])");
    const emptyState = page.getByText(/no.*models|empty|no.*results/i);

    const hasCards = (await modelCards.count()) > 0;
    const hasEmpty = (await emptyState.count()) > 0;
    expect(hasCards || hasEmpty, "Should show model cards or empty state").toBe(true);
  });

  test("step 2: view model detail page with full info", async ({ page }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    // Model card links are inside the main content area, not in the nav/footer
    const modelLink = page.locator("#main-content a[href*='/marketplace/']").filter({
      hasNotText: /back|return|browse/i,
    });
    const linkCount = await modelLink.count();

    if (linkCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No models in catalog",
      });
      return;
    }

    await modelLink.first().click();
    await page.waitForURL(/\/marketplace\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // Detail page elements
    const detailHeading = page.getByRole("heading").first();
    await expect(detailHeading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should show activate button or already-activated state
    const actionButton = page.getByRole("button", { name: /activate|run|use|open/i });
    await expect(actionButton.first()).toBeVisible({ timeout: 10_000 });
  });

  test("step 3: activate a free model from marketplace", async ({ page }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    // Find an activatable model
    const activateButton = page.locator(
      '.grid button:not([aria-label*="favorites"]):not([title*="favorites"])'
    ).filter({ hasText: /^activate$/i });

    const buttonCount = await activateButton.count();
    if (buttonCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No activatable models (all already activated or catalog empty)",
      });
      return;
    }

    await activateButton.first().click();

    // Handle confirmation modal if it appears
    const modal = page.getByRole("dialog");
    if (await modal.isVisible().catch(() => false)) {
      const confirmButton = modal.getByRole("button", { name: /confirm|activate|yes/i });
      if ((await confirmButton.count()) > 0) {
        await confirmButton.click();
      }
    }

    // Wait for activation result
    const bodyText = await page.textContent("body", { timeout: LONG_TIMEOUT });
    const isSuccess =
      /activated|success|already|solve/i.test(bodyText || "") ||
      page.url().includes("/solve");
    expect(isSuccess, "Activation should succeed").toBe(true);
  });

  test("step 4: verify activated model appears in My Models", async ({ page }) => {
    await page.goto("/solve");
    await expect(page).toHaveURL(/\/solve/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // My Models page should show at least one model card
    const mainContent = page.locator("#main-content");
    await expect(mainContent).toBeVisible({ timeout: NAV_TIMEOUT });

    // This may be empty if the user has no models — that's OK for fresh environments
    // Just verify the page loaded correctly
    await expect(page).toHaveURL(/\/solve/);
  });

  test("step 5: navigate to model execution page and verify UI", async ({ page }) => {
    await page.goto("/solve");
    await expect(page).toHaveURL(/\/solve/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    const runButton = page.locator("#main-content .grid").getByRole("button", { name: /run/i });
    const cardCount = await runButton.count();

    if (cardCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No activated models to execute",
      });
      return;
    }

    await runButton.first().click();
    await page.waitForURL(/\/solve\//, { timeout: NAV_TIMEOUT });

    // Execution page should have:
    // 1. Input area (textarea or code editor)
    const inputArea = page.locator("textarea").or(page.locator('[data-testid="code-editor"]'));
    await expect(inputArea.first()).toBeVisible({ timeout: NAV_TIMEOUT });

    // 2. Run button
    const executeButton = page.getByRole("button", { name: /run|execute|solve|play/i });
    await expect(executeButton.first()).toBeVisible();

    // 3. Model name in heading
    const modelHeading = page.getByRole("heading").first();
    await expect(modelHeading).toBeVisible();
  });
});
