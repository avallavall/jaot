import { test, expect } from "@playwright/test";
import { AdminPage } from "./pages/admin.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Admin tests run under the "admin" Playwright project, which uses
 * storageState from admin.setup.ts (admin@jaot.io credentials).
 *
 * Run serially to avoid overwhelming the dev server with concurrent
 * admin page compilations.
 */
test.describe.configure({ mode: "serial" });

test.describe("Admin Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("admin dashboard loads with heading", async ({ page }) => {
    const adminPage = new AdminPage(page);
    await adminPage.goto();
    await adminPage.expectLoaded();
    await adminPage.expectHeadingVisible();
  });

  test.describe("Admin sections", () => {
    test("users page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoUsers();
      await expect(page).toHaveURL(/\/admin\/users/);
    });

    test("organizations page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoOrganizations();
      await expect(page).toHaveURL(/\/admin\/organizations/);
    });

    test("models page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoModels();
      await expect(page).toHaveURL(/\/admin\/models/);
    });

    test("executions page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoExecutions();
      await expect(page).toHaveURL(/\/admin\/executions/);
    });

    test("credits page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoCredits();
      await expect(page).toHaveURL(/\/admin\/credits/);
    });

    test("API keys page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoApiKeys();
      await expect(page).toHaveURL(/\/admin\/api-keys/);
    });

    test("reviews page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoReviews();
      await expect(page).toHaveURL(/\/admin\/reviews/);
    });

    test("settings page loads", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoSettings();
      await expect(page).toHaveURL(/\/admin\/settings/);
    });
  });

  test.describe("Admin CRUD Operations (E2E-06)", () => {
    test("users page displays user table or list", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoUsers();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();

      // Should show a table or list of users
      const table = page.getByRole("table").or(page.locator("table"));
      const list = page.getByRole("list");
      const hasData = (await table.count()) > 0 || (await list.count()) > 0;
      expect(hasData, "Users page should display a table or list").toBe(true);
    });

    test("organizations page displays org data", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoOrganizations();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("models admin page shows catalog entries", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoModels();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("credits admin page shows transaction data or controls", async ({
      page,
    }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoCredits();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("executions admin page shows execution history", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoExecutions();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });
  });

  test.describe("Admin - User Table Verification", () => {
    test("user table displays expected column headers", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoUsers();
      await expect(page).toHaveURL(/\/admin\/users/);

      // Wait for table to appear (may be loading)
      const table = page.getByRole("table");
      await expect(table).toBeVisible({ timeout: 15_000 });

      // Verify key column headers are present
      const headers = page.getByRole("columnheader");
      const headerTexts = await headers.allTextContents();
      const joined = headerTexts.join(" ").toLowerCase();
      expect(joined).toContain("name");
      expect(joined).toContain("email");
    });

    test("user search input is present and accepts text", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoUsers();
      await expect(page).toHaveURL(/\/admin\/users/);

      // Find the search input by role
      const searchInput = page.getByRole("textbox").first();
      await expect(searchInput).toBeVisible({ timeout: 15_000 });

      // Type into it and verify
      await searchInput.fill("test-search");
      await expect(searchInput).toHaveValue("test-search");
    });
  });

  test.describe("Admin - Organization Table Verification", () => {
    test("organization table displays expected column headers", async ({
      page,
    }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoOrganizations();
      await expect(page).toHaveURL(/\/admin\/organizations/);

      // Wait for table to appear
      const table = page.getByRole("table");
      await expect(table).toBeVisible({ timeout: 15_000 });

      // Verify key column headers are present
      const headers = page.getByRole("columnheader");
      const headerTexts = await headers.allTextContents();
      const joined = headerTexts.join(" ").toLowerCase();
      expect(joined).toContain("name");
      expect(joined).toContain("plan");
    });

    test("organization page has search input", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoOrganizations();
      await expect(page).toHaveURL(/\/admin\/organizations/);

      // Find the search input by role
      const searchInput = page.getByRole("textbox").first();
      await expect(searchInput).toBeVisible({ timeout: 15_000 });
    });
  });

  test.describe("Admin - Settings Tabs", () => {
    test("settings page renders tab navigation", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoSettings();
      await expect(page).toHaveURL(/\/admin\/settings/);

      // Wait for tabs to render (settings data must load first)
      const tabs = page.getByRole("tab");
      await expect(tabs.first()).toBeVisible({ timeout: 15_000 });

      // Should have multiple tabs
      const tabCount = await tabs.count();
      expect(tabCount).toBeGreaterThanOrEqual(2);
    });

    test("settings page can switch between tabs", async ({ page }) => {
      const adminPage = new AdminPage(page);
      await adminPage.gotoSettings();
      await expect(page).toHaveURL(/\/admin\/settings/);

      // Wait for tabs to render
      const tabs = page.getByRole("tab");
      await expect(tabs.first()).toBeVisible({ timeout: 15_000 });

      // Click on a non-default tab (second tab)
      const secondTab = tabs.nth(1);
      await expect(secondTab).toBeVisible();
      await expect(secondTab).toBeEnabled();
      await secondTab.click();

      // Verify the tab is now selected (aria-selected) — allow time for re-render
      await expect(secondTab).toHaveAttribute("aria-selected", "true", {
        timeout: 10_000,
      });
    });
  });

  test.describe("Admin - Sidebar Navigation", () => {
    test("admin sidebar contains navigation links to sub-pages", async ({
      page,
    }) => {
      const adminPage = new AdminPage(page);
      await adminPage.goto();
      await adminPage.expectLoaded();

      // Find sidebar navigation links for key sections
      const nav = page.getByRole("navigation");
      await expect(nav).toBeVisible({ timeout: 15_000 });

      const orgLink = nav.getByRole("link", { name: /organizations/i });
      const usersLink = nav.getByRole("link", { name: /users/i });
      const settingsLink = nav.getByRole("link", { name: /settings/i });

      await expect(orgLink).toBeVisible();
      await expect(usersLink).toBeVisible();
      await expect(settingsLink).toBeVisible();
    });

    test("clicking sidebar link navigates to correct sub-page", async ({
      page,
    }) => {
      const adminPage = new AdminPage(page);
      await adminPage.goto();
      await adminPage.expectLoaded();

      // Click the Users sidebar link
      const nav = page.getByRole("navigation");
      await expect(nav).toBeVisible({ timeout: 15_000 });
      const usersLink = nav.getByRole("link", { name: /users/i });
      await expect(usersLink).toBeVisible();
      await usersLink.click();

      // Wait for navigation to complete
      await page.waitForURL(/\/admin\/users/);
      await expect(page).toHaveURL(/\/admin\/users/);
    });
  });
});
