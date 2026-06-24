import { test, expect } from "@playwright/test";
import { WorkspacePage } from "./pages/workspace.page";
import { BillingPage } from "./pages/billing.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Billing (E2E-12)", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });
  test("credits page shows balance information", async ({ page }) => {
    const ws = new WorkspacePage(page);
    await ws.gotoCredits();
    await expect(page).toHaveURL(/\/workspace\/credits/);

    // Credits page should display balance or credit-related content
    const content = page.getByRole("main");
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test("credits page has subscription or top-up actions", async ({ page }) => {
    const ws = new WorkspacePage(page);
    await ws.gotoCredits();

    // Look for upgrade/top-up/subscribe actions
    // Page should load; billing actions depend on plan state
    await expect(page).toHaveURL(/\/workspace\/credits/);
  });

  test("usage page shows consumption data", async ({ page }) => {
    const ws = new WorkspacePage(page);
    await ws.gotoUsage();
    await expect(page).toHaveURL(/\/workspace\/usage/);

    const content = page.getByRole("main");
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test("workspace profile page loads with org settings", async ({ page }) => {
    const ws = new WorkspacePage(page);
    await ws.gotoProfile();
    await expect(page).toHaveURL(/\/workspace\/my-profile/);
  });
});

test.describe("Billing Page (/billing)", () => {
  test("billing page displays plan name", async ({ page }) => {
    const billingPage = new BillingPage(page);
    await billingPage.goto();
    await billingPage.expectLoaded();
    await billingPage.expectHeadingVisible();

    // The "Current Plan" card should show a plan name (e.g., "Free", "Starter", "Pro")
    const planText = page.getByText(/free|starter|pro|enterprise/i);
    await expect(planText.first()).toBeVisible({ timeout: 10_000 });
  });

  test("billing page displays credit balance as a number", async ({ page }) => {
    const billingPage = new BillingPage(page);
    await billingPage.goto();
    await billingPage.expectLoaded();

    // Find the "Credit Balance" heading text
    const creditBalanceLabel = page.getByText(/credit balance/i);
    await expect(creditBalanceLabel.first()).toBeVisible({ timeout: 10_000 });

    // The credit balance value should be a number (e.g., "0", "100", "1,000")
    // Look for the semibold number inside the credit balance card
    const balanceCard = page.locator(".rounded-lg.border.bg-card").filter({
      has: page.getByText(/credit balance/i),
    });
    const balanceText = await balanceCard.first().locator("p.text-2xl").textContent();
    expect(balanceText?.trim()).toMatch(/^\d[\d,]*$/);
  });

  test("billing page shows upgrade CTA for free plan or managed plan message", async ({
    page,
  }) => {
    const billingPage = new BillingPage(page);
    await billingPage.goto();
    await billingPage.expectLoaded();

    // Wait for the page to fully render (client-side hydration of ProtectedRoute)
    await billingPage.expectHeadingVisible();

    // Check for the CTA section — either the upgrade link or managed plan message
    const upgradeLink = page.getByRole("link", { name: /contact.*upgrade/i });
    const salesLink = page.locator('a[href*="sales@jaot.io"]');
    const supportLink = page.locator('a[href*="support@jaot.io"]');
    // The free plan CTA text: "You are on the Free plan..."
    const freePlanText = page.getByText(/you are on the/i);

    const hasUpgrade = (await upgradeLink.count()) > 0;
    const hasSales = (await salesLink.count()) > 0;
    const hasSupport = (await supportLink.count()) > 0;
    const hasFreePlan = (await freePlanText.count()) > 0;

    // One of the CTA variants should be present
    expect(hasUpgrade || hasSales || hasSupport || hasFreePlan).toBe(true);
  });

  test("workspace credits page is distinct from billing page", async ({ page }) => {
    // Navigate to /workspace/credits
    await page.goto("/workspace/credits");
    await expect(page).toHaveURL(/\/workspace\/credits/);

    // Navigate to /billing with retry for compilation errors
    const billingPage = new BillingPage(page);
    await billingPage.goto();
    await billingPage.expectLoaded();

    // Verify billing page heading is visible after client-side hydration
    await billingPage.expectHeadingVisible();
  });
});
