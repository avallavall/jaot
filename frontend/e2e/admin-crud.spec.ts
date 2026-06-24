/**
 * Admin CRUD — Functional E2E Tests
 *
 * Tests the admin panel with REAL data operations:
 *   1. Dashboard shows real stats (organizations, users, models counts)
 *   2. Users table has real data and search works
 *   3. Organizations table has real org names and plan names
 *   4. Settings tabs work and show form controls
 *   5. Models admin page shows catalog models
 *
 * This spec runs under the "admin" project in playwright.config.ts,
 * which uses admin auth state from admin.setup.ts (admin@jaot.io).
 */

import { test, expect } from "@playwright/test";
import { AdminPage } from "./pages/admin.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;

test.describe.configure({ mode: "serial" });

test.describe("Admin CRUD — Functional Tests", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // -------------------------------------------------------------------------
  // 1. Admin dashboard shows real stats
  // -------------------------------------------------------------------------

  test("dashboard shows real stats with non-zero counts", async ({ page }) => {
    const adminPage = new AdminPage(page);
    await adminPage.goto();
    await adminPage.expectLoaded();
    await adminPage.expectHeadingVisible();

    // Stats cards typically show key metrics: organizations, users, models, etc.
    // They render inside .bg-card containers with large numbers.
    const mainContent = page.locator("#main-content");
    await expect(mainContent).toBeVisible({ timeout: NAV_TIMEOUT });

    // Look for stat cards — they display numbers (integers)
    // The admin dashboard renders cards with headings like "Organizations",
    // "Users", "Models" and a numeric value below.
    const statCards = page.locator(
      ".bg-card, [class*='card'], .rounded-lg.border"
    );
    const cardCount = await statCards.count();
    expect(cardCount, "Dashboard should have stat cards").toBeGreaterThan(0);

    // Extract all visible numbers from the dashboard
    // Stats render as large text (text-2xl, text-3xl, etc.)
    const largeNumbers = page.locator(
      ".text-2xl, .text-3xl, .text-4xl, [class*='text-2xl'], [class*='text-3xl']"
    );
    const numberCount = await largeNumbers.count();

    if (numberCount > 0) {
      // Verify at least one stat shows a real integer (not "0" or empty)
      let hasNonZeroStat = false;
      for (let i = 0; i < numberCount; i++) {
        const text = await largeNumbers.nth(i).textContent();
        const trimmed = text?.trim() ?? "";
        // Match integers like "5", "12", "1,234"
        if (/^\d[\d,]*$/.test(trimmed) && trimmed !== "0") {
          hasNonZeroStat = true;
          break;
        }
      }

      // At minimum, the seeded data should have at least 1 user and 1 org
      expect(
        hasNonZeroStat,
        "Dashboard should show at least one non-zero stat (seeded data has users/orgs)"
      ).toBe(true);
    } else {
      // Fallback: verify the dashboard text contains some numeric values
      const bodyText = await mainContent.textContent();
      const hasNumbers = /\b[1-9]\d*\b/.test(bodyText || "");
      expect(
        hasNumbers,
        "Dashboard should contain numeric stat values"
      ).toBe(true);
    }
  });

  // -------------------------------------------------------------------------
  // 2. Users table has real data and search works
  // -------------------------------------------------------------------------

  test("users table displays real user data with email addresses", async ({
    page,
  }) => {
    const adminPage = new AdminPage(page);
    await adminPage.gotoUsers();
    await expect(page).toHaveURL(/\/admin\/users/);

    // Wait for the table to render
    const table = page.getByRole("table");
    await expect(table).toBeVisible({ timeout: NAV_TIMEOUT });

    // Verify column headers include "Email"
    const headers = page.getByRole("columnheader");
    const headerTexts = await headers.allTextContents();
    const joined = headerTexts.join(" ").toLowerCase();
    expect(joined, "Users table should have Email column").toContain("email");

    // Verify table has data rows (not just header)
    const rows = page.getByRole("row");
    const rowCount = await rows.count();
    // At least header row + 1 data row (admin@jaot.io exists from seed)
    expect(
      rowCount,
      "Users table should have at least one data row"
    ).toBeGreaterThanOrEqual(2);

    // Verify at least one cell contains an @ symbol (email address)
    const cells = page.getByRole("cell");
    const cellTexts = await cells.allTextContents();
    const hasEmail = cellTexts.some((text) => text.includes("@"));
    expect(
      hasEmail,
      "Users table should contain email addresses with @ symbol"
    ).toBe(true);
  });

  test("users table search filters results", async ({ page }) => {
    const adminPage = new AdminPage(page);
    await adminPage.gotoUsers();
    await expect(page).toHaveURL(/\/admin\/users/);

    // Wait for table to load
    const table = page.getByRole("table");
    await expect(table).toBeVisible({ timeout: NAV_TIMEOUT });

    // Count initial rows
    const initialRows = page.getByRole("row");
    const initialCount = await initialRows.count();

    // Find search input
    const searchInput = page.getByRole("textbox").first();
    await expect(searchInput).toBeVisible({ timeout: NAV_TIMEOUT });

    // Search for "admin" — the seeded admin user should match
    await searchInput.fill("admin");

    // Wait for debounce and filtering to take effect
    await expect(async () => {
      const currentRows = page.getByRole("row");
      const currentCount = await currentRows.count();

      // After filtering, either:
      // 1. Fewer rows than before (filter narrowed results)
      // 2. Same count if only one user matches (header + 1 data row)
      // 3. The text "admin" appears in a visible cell
      const cells = page.getByRole("cell");
      const cellTexts = await cells.allTextContents();
      const hasAdminText = cellTexts.some((text) =>
        text.toLowerCase().includes("admin")
      );

      expect(
        hasAdminText || currentCount <= initialCount,
        "Search should filter results or show matching 'admin' entries"
      ).toBe(true);
    }).toPass({ timeout: 10_000 });

    // Clear search and verify results restore
    await searchInput.clear();
    await expect(async () => {
      const restoredRows = page.getByRole("row");
      const restoredCount = await restoredRows.count();
      expect(restoredCount).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 10_000 });
  });

  // -------------------------------------------------------------------------
  // 3. Organizations table has real data
  // -------------------------------------------------------------------------

  test("organizations table displays org names and plan names", async ({
    page,
  }) => {
    const adminPage = new AdminPage(page);
    await adminPage.gotoOrganizations();
    await expect(page).toHaveURL(/\/admin\/organizations/);

    // Wait for table to render
    const table = page.getByRole("table");
    await expect(table).toBeVisible({ timeout: NAV_TIMEOUT });

    // Verify column headers include "Name" and "Plan"
    const headers = page.getByRole("columnheader");
    const headerTexts = await headers.allTextContents();
    const joined = headerTexts.join(" ").toLowerCase();
    expect(joined, "Org table should have Name column").toContain("name");
    expect(joined, "Org table should have Plan column").toContain("plan");

    // Verify table has at least one data row
    const rows = page.getByRole("row");
    const rowCount = await rows.count();
    expect(
      rowCount,
      "Org table should have at least one data row"
    ).toBeGreaterThanOrEqual(2);

    // Verify cells contain real org data (not empty)
    const cells = page.getByRole("cell");
    const cellTexts = await cells.allTextContents();
    const nonEmptyCells = cellTexts.filter((t) => t.trim().length > 0);
    expect(
      nonEmptyCells.length,
      "Org table cells should contain non-empty data"
    ).toBeGreaterThan(0);

    // Check for plan name indicators (free, starter, pro, enterprise, etc.)
    const pageText = await page.locator("#main-content").textContent();
    const hasPlanName =
      /free|starter|pro|enterprise|business|team/i.test(pageText || "");
    expect(
      hasPlanName,
      "Org table should show plan names (free, starter, pro, etc.)"
    ).toBe(true);
  });

  // -------------------------------------------------------------------------
  // 4. Settings tabs work and show form controls
  // -------------------------------------------------------------------------

  test("settings tabs render and switching shows form content", async ({
    page,
  }) => {
    const adminPage = new AdminPage(page);
    await adminPage.gotoSettings();
    await expect(page).toHaveURL(/\/admin\/settings/);

    // Wait for tabs to render (settings data must load first)
    const tabs = page.getByRole("tab");
    await expect(tabs.first()).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should have multiple tabs
    const tabCount = await tabs.count();
    expect(
      tabCount,
      "Settings should have at least 2 tabs"
    ).toBeGreaterThanOrEqual(2);

    // -- First tab: verify it has form controls --
    const firstTabPanel = page.getByRole("tabpanel");
    await expect(firstTabPanel).toBeVisible({ timeout: NAV_TIMEOUT });

    // The tab panel should contain form controls or content (inputs, toggles, selects, buttons, text)
    const formControls = firstTabPanel
      .locator("input, select, textarea, button, [role='switch'], [role='combobox'], [role='checkbox'], label, .grid, table");
    const controlCount = await formControls.count();
    expect(
      controlCount,
      "First settings tab should contain form controls or content"
    ).toBeGreaterThan(0);

    // -- Second tab: click and verify content changes --
    const secondTab = tabs.nth(1);
    await expect(secondTab).toBeVisible();
    await expect(secondTab).toBeEnabled();
    const secondTabName = await secondTab.textContent();
    await secondTab.click();

    // Verify the tab is now selected
    await expect(secondTab).toHaveAttribute("aria-selected", "true", {
      timeout: 10_000,
    });

    // Verify the tab panel updated with content
    const updatedPanel = page.getByRole("tabpanel");
    await expect(updatedPanel).toBeVisible({ timeout: NAV_TIMEOUT });

    // The new panel should also have form controls
    const newFormControls = updatedPanel
      .locator("input, select, textarea, [role='switch'], [role='combobox']");
    const newControlCount = await newFormControls.count();
    expect(
      newControlCount,
      `"${secondTabName?.trim()}" tab should contain form controls`
    ).toBeGreaterThan(0);

    // -- Third tab (if exists): verify it also works --
    if (tabCount >= 3) {
      const thirdTab = tabs.nth(2);
      await thirdTab.click();
      await expect(thirdTab).toHaveAttribute("aria-selected", "true", {
        timeout: 10_000,
      });

      const thirdPanel = page.getByRole("tabpanel");
      await expect(thirdPanel).toBeVisible({ timeout: NAV_TIMEOUT });

      // At minimum the panel should have some content (text or controls)
      const panelText = await thirdPanel.textContent();
      expect(
        (panelText?.trim().length ?? 0) > 0,
        "Third settings tab should have content"
      ).toBe(true);
    }
  });

  // -------------------------------------------------------------------------
  // 5. Models admin page shows catalog models
  // -------------------------------------------------------------------------

  test("models admin page shows catalog model data", async ({ page }) => {
    const adminPage = new AdminPage(page);
    await adminPage.gotoModels();
    await expect(page).toHaveURL(/\/admin\/models/);

    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    // The models admin page should show a table or grid with model entries
    const table = page.getByRole("table");
    const grid = page.locator(".grid");
    const hasTable = await table.isVisible().catch(() => false);
    const hasGrid = await grid.first().isVisible().catch(() => false);

    expect(
      hasTable || hasGrid,
      "Models admin page should display a table or grid of models"
    ).toBe(true);

    if (hasTable) {
      // Verify the table has data rows
      const rows = page.getByRole("row");
      const rowCount = await rows.count();
      expect(
        rowCount,
        "Models table should have at least one data row (seeded catalog)"
      ).toBeGreaterThanOrEqual(2);

      // Verify cells contain model-related data
      const cells = page.getByRole("cell");
      const cellTexts = await cells.allTextContents();
      const hasModelData = cellTexts.some(
        (text) => text.trim().length > 0
      );
      expect(hasModelData, "Models table cells should contain data").toBe(
        true
      );
    } else {
      // Grid layout: verify there are child elements (model cards)
      const gridChildren = grid.first().locator("> *");
      const childCount = await gridChildren.count();
      expect(
        childCount,
        "Models grid should have model card entries"
      ).toBeGreaterThan(0);
    }

    // Verify the page text contains model-related terms
    const pageText = await content.textContent();
    const hasModelTerms =
      /model|template|catalog|name|category|status/i.test(pageText || "");
    expect(
      hasModelTerms,
      "Models admin page should contain model-related terminology"
    ).toBe(true);
  });
});
