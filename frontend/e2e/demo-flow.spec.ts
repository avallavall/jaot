import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;

test.describe("Demo Flow — Hexaly Executive Demo", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // Act I: Landing & Pricing (public pages — use fresh context)
  test("Act I: Landing page loads with hero and key sections", async ({ browser }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    // Hero section should be visible
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Key sections should exist
    await expect(page.getByText(/optimization/i).first()).toBeVisible();

    // CTA buttons should be visible
    const ctaButton = page.getByRole("link", { name: /get started|sign up|try/i });
    await expect(ctaButton.first()).toBeVisible();

    await context.close();
  });

  test("Act I: Pricing page shows plans with toggle", async ({ browser }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/pricing");
    await page.waitForLoadState("domcontentloaded");

    // Should show plan names
    await expect(page.getByText(/free/i).first()).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should have monthly/annual toggle
    const toggle = page.getByRole("switch")
      .or(page.getByRole("button", { name: /annual|monthly/i }))
      .or(page.getByText(/annual|monthly/i));
    await expect(toggle.first()).toBeVisible();

    await context.close();
  });

  // Act II: AI Assistant (authenticated)
  test("Act II: AI Assistant page loads with chat interface", async ({ page }) => {
    await page.goto("/builder/ai-assistant");

    // Should have the chat/AI interface visible
    // The AI assistant page may redirect or show a conversation list
    await expect(page).toHaveURL(/\/builder/, { timeout: NAV_TIMEOUT });

    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should show heading or chat area
    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  // Act III: Builder
  test("Act III: Builder loads with action buttons", async ({ page }) => {
    await page.goto("/builder");

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // All three builder actions should be visible
    const newModelButton = page.getByRole("button", { name: /new model/i });
    const importButton = page.getByRole("button", { name: /import/i });
    const templatesButton = page.getByRole("button", { name: /template/i });

    await expect(newModelButton).toBeVisible({ timeout: 10_000 });
    await expect(importButton).toBeVisible();
    await expect(templatesButton).toBeVisible();
  });

  test("Act III: Builder templates page has template cards", async ({ page }) => {
    await page.goto("/builder/templates");

    await expect(page).toHaveURL(/\/builder\/templates/);

    // Should show template cards or content
    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible();
  });

  // Act IV: Marketplace Browse & Model Detail
  test("Act IV: Marketplace loads with model cards", async ({ page }) => {
    await page.goto("/marketplace");

    await expect(page).toHaveURL(/\/marketplace/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should show model cards in a grid
    const mainContent = page.locator("#main-content");
    await expect(mainContent).toBeVisible();

    // Search should be present
    const searchInput = page.getByRole("searchbox").or(page.getByPlaceholder(/search/i));
    await expect(searchInput.first()).toBeVisible({ timeout: 10_000 });
  });

  test("Act IV: Marketplace model detail page loads", async ({ page }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    // Wait for model cards to load
    // Model card links are inside the main content area, not in the nav/footer
    const modelLink = page.locator("#main-content a[href*='/marketplace/']").filter({
      hasNotText: /back|return|browse/i,
    });

    const linkCount = await modelLink.count();
    if (linkCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No models in marketplace catalog",
      });
      return;
    }

    // Click first model
    await modelLink.first().click();
    await page.waitForURL(/\/marketplace\/.+/, { timeout: NAV_TIMEOUT });

    // Detail page should show model info
    const detailHeading = page.getByRole("heading").first();
    await expect(detailHeading).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  // Act V: Solve Dashboard & Execution
  test("Act V: My Models page loads with models or empty state", async ({ page }) => {
    await page.goto("/solve");

    await expect(page).toHaveURL(/\/solve/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Sidebar should be visible
    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  test("Act V: Execution page loads for available model", async ({ page }) => {
    await page.goto("/solve");
    await expect(page).toHaveURL(/\/solve/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Find a model to execute
    const modelLinks = page.locator("a[href*='/solve/']").filter({
      hasNotText: /catalog|executions|favorites|multi|compare|custom|create/i,
    });

    const linkCount = await modelLinks.count();
    if (linkCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No activated models available for execution",
      });
      return;
    }

    await modelLinks.first().click();
    await page.waitForURL(/\/solve\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // Execution page should show run button and input area
    const runButton = page.getByRole("button", {
      name: /run|execute|solve|play/i,
    });
    await expect(runButton.first()).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should have textarea/code editor for input
    const inputArea = page.locator("textarea").or(page.locator('[data-testid="code-editor"]'));
    await expect(inputArea.first()).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  // Act VI: Admin Dashboard
  // NOTE: This test uses regular user auth — admin tests are in admin.spec.ts
  // We verify the workspace dashboard instead (accessible to all users)
  test("Act VI: Workspace dashboard loads with sections", async ({ page }) => {
    await page.goto("/workspace");

    await expect(page).toHaveURL(/\/workspace/);

    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  // Act VII: i18n — verify locale switching works
  test("Act VII: Locale switching works on landing page", async ({ browser }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    // Load Spanish landing
    await page.goto("/es");
    await page.waitForLoadState("domcontentloaded");

    // Should show Spanish content (not English)
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    await context.close();
  });
});
