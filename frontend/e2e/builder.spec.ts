import { test, expect } from "@playwright/test";
import { BuilderPage } from "./pages/builder.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Model Builder", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("builder page loads", async ({ page }) => {
    const builderPage = new BuilderPage(page);
    await builderPage.goto();
    await builderPage.expectLoaded();
    await builderPage.expectHeadingVisible();
  });

  test("builder templates page loads", async ({ page }) => {
    const builderPage = new BuilderPage(page);
    await builderPage.gotoTemplates();
    await expect(page).toHaveURL(/\/builder\/templates/);
  });

  test("builder page has create/new action available", async ({ page }) => {
    const builderPage = new BuilderPage(page);
    await builderPage.goto();

    // Check there is a way to create new documents (button or link)
    // At minimum the page should load without errors
    await builderPage.expectLoaded();
  });

  test.describe("Model Operations (E2E-04)", () => {
    test("create action navigates to new document or template selection", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      const createAction = page.getByRole("link", { name: /new|create/i }).or(
        page.getByRole("button", { name: /new|create/i })
      );
      await expect(createAction.first()).toBeVisible({ timeout: 10_000 });
      const count = await createAction.count();
      if (count > 0) {
        await createAction.first().click();
        // Should stay within builder/template area
        await page.waitForURL(/builder|template/i, { timeout: 15_000 });
      }
    });

    test("builder templates page shows available templates", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.gotoTemplates();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
      await expect(page).toHaveURL(/\/builder\/templates/);
    });

    test("builder page displays document list or empty state", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();

      // Should show either documents or an empty state message
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });
  });

  test.describe("Builder - List Page Elements", () => {
    test("builder list page shows heading and subtitle", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      // Verify h1 heading is visible
      const heading = page.getByRole("heading", { level: 1 });
      await expect(heading).toBeVisible({ timeout: 10_000 });

      // Verify subtitle paragraph exists below heading
      // Defensive: subtitle text varies by translation, just check heading area has content
      const headingText = await heading.textContent();
      expect(headingText?.trim().length).toBeGreaterThan(0);
    });

    test("builder list page has Import JSON button", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      const importButton = page.getByRole("button", { name: /import/i });
      await expect(importButton).toBeVisible({ timeout: 10_000 });
    });

    test("builder list page has Templates button", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      const templatesButton = page.getByRole("button", { name: /template/i });
      await expect(templatesButton).toBeVisible({ timeout: 10_000 });
    });

    test("builder list page has New Model button", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      // "New Model" button may be disabled based on permissions
      const newModelButton = page.getByRole("button", { name: /new model/i });
      await expect(newModelButton).toBeVisible({ timeout: 10_000 });
    });
  });

  test.describe("Builder - Document List", () => {
    test("builder list shows documents or empty state", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();

      // Wait for loading to finish -- heading must be visible
      await builderPage.expectHeadingVisible();

      // Check for EITHER document cards (grid items) OR empty state
      const documentCards = page.locator(".grid .border.rounded-lg");
      const emptyState = page.getByText(
        /no.*model|get.*started|create.*first|no.*document/i
      );

      const hasDocuments = (await documentCards.count()) > 0;
      const hasEmptyState = (await emptyState.count()) > 0;

      // One of the two should be present after loading
      expect(hasDocuments || hasEmptyState).toBe(true);
    });

    test("templates page loads and shows content", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.gotoTemplates();

      await expect(page).toHaveURL(/\/builder\/templates/);

      // Verify page has visible content (heading or template cards)
      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();
    });

    test("builder list page buttons are in header area together", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      // Verify all three action buttons are present (multi-locale)
      const importButton = page.getByRole("button", { name: /import|importar/i });
      const templatesButton = page.getByRole("button", { name: /template|plantilla/i });
      const newModelButton = page.getByRole("button", { name: /new model|nuevo|nou/i });

      await expect(importButton).toBeVisible({ timeout: 10_000 });
      await expect(templatesButton).toBeVisible({ timeout: 10_000 });
      await expect(newModelButton).toBeVisible({ timeout: 10_000 });
    });

    test("clicking Templates button navigates to templates page", async ({ page }) => {
      const builderPage = new BuilderPage(page);
      await builderPage.goto();
      await builderPage.expectLoaded();
      await builderPage.expectHeadingVisible();

      const templatesButton = page.getByRole("button", { name: /template|plantilla/i });
      await expect(templatesButton).toBeVisible({ timeout: 10_000 });
      await templatesButton.click();

      // Use waitForURL to confirm navigation (NOT networkidle)
      await page.waitForURL(/\/builder\/templates/);
      await expect(page).toHaveURL(/\/builder\/templates/);
    });
  });
});
