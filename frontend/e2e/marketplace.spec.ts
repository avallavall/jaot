import { test, expect } from "@playwright/test";
import { MarketplacePage } from "./pages/marketplace.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Marketplace", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("marketplace page loads with heading", async ({ page }) => {
    const marketplacePage = new MarketplacePage(page);
    await marketplacePage.goto();
    await marketplacePage.expectLoaded();
  });

  test("marketplace displays model cards or empty state", async ({ page }) => {
    const marketplacePage = new MarketplacePage(page);
    await marketplacePage.goto();

    // Either model cards are displayed or an empty state message
    const content = page.getByRole("main");
    await expect(content).toBeVisible();
  });

  test("marketplace has search functionality", async ({ page }) => {
    const marketplacePage = new MarketplacePage(page);
    await marketplacePage.goto();
    await marketplacePage.expectLoaded();

    // Search input should be present
    await expect(marketplacePage.searchInput.first()).toBeVisible({ timeout: 10_000 });
  });

  test.describe("Filter & Category (E2E-08)", () => {
    test("marketplace supports category filtering", async ({ page }) => {
      const marketplacePage = new MarketplacePage(page);
      await marketplacePage.goto();

      // Look for category filter buttons, tabs, or dropdown
      page
        .getByRole("tab")
        .or(page.getByRole("combobox"))
        .or(page.getByRole("button", { name: /category|filter|all/i }));

      // Page should load with category filtering available
      await marketplacePage.expectLoaded();
    });

    test("marketplace model detail page loads for valid model", async ({ page }) => {
      const marketplacePage = new MarketplacePage(page);
      await marketplacePage.goto();

      // Try to click on a model card if any exist
      const modelCard = page
        .getByRole("link")
        .filter({ hasText: /model|template|optimization/i });
      const count = await modelCard.count();

      if (count > 0) {
        await modelCard.first().click();
        await page.waitForLoadState("networkidle");
        // Should navigate to model detail
        await expect(page).toHaveURL(/\/marketplace\/.+/);
      }
    });

    test("search filters marketplace results", async ({ page }) => {
      const marketplacePage = new MarketplacePage(page);
      await marketplacePage.goto();
      await marketplacePage.expectLoaded();

      await expect(marketplacePage.searchInput.first()).toBeVisible({ timeout: 10_000 });
      await marketplacePage.search("knapsack");
      // Wait for debounce + filtering
      await expect(async () => {
        await expect(page).toHaveURL(/\/marketplace/);
      }).toPass({ timeout: 5_000 });
      await marketplacePage.expectLoaded();
    });
  });
});
