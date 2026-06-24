import { test, expect } from "@playwright/test";

/**
 * Sidebar navigation verification tests.
 *
 * Runs against the real authenticated backend (chromium project storageState
 * from global.setup.ts). Auth is provided via the user.json cookie — no API
 * mocking. See plan 11-05 (P11-REFACTOR-09).
 *
 * Current sidebar structure (as of 2026-03):
 *   BUILD: My Models, Create Model, Visual Builder, Templates, AI Assistant, Multi-Objective
 *   DISCOVER: Marketplace, For Sellers
 *   Bottom bar: Res..., EN, help, dark mode, Logout
 */

test.describe("Sidebar Navigation Structure", () => {
  // chromium project storageState (user.json) provides auth automatically —
  // no test.use({ storageState }) override needed.

  test("sidebar renders Build section with all 6 items", async ({ page }) => {
    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    // Verify Build section header
    await expect(sidebar.getByText("Build", { exact: true })).toBeVisible();

    // Verify all 6 Build items
    await expect(sidebar.getByText("My Models")).toBeVisible();
    await expect(sidebar.getByText("Create Model")).toBeVisible();
    await expect(sidebar.getByText("Visual Builder")).toBeVisible();
    await expect(sidebar.getByText("Templates")).toBeVisible();
    await expect(sidebar.getByText("AI Assistant")).toBeVisible();
    await expect(sidebar.getByText("Multi-Objective")).toBeVisible();
  });

  test("sidebar renders Discover section with items", async ({ page }) => {
    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await expect(sidebar.getByText("Discover", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("Marketplace")).toBeVisible();
    await expect(sidebar.getByText("For Sellers")).toBeVisible();
  });

  test("sidebar has logout button", async ({ page }) => {
    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await expect(sidebar.getByText("Logout")).toBeVisible();
  });

  test("sidebar has language selector", async ({ page }) => {
    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await expect(sidebar.getByText("EN")).toBeVisible();
  });

  test("sidebar renders both Build and Discover sections", async ({ page }) => {
    // Both sections are visible for regular authenticated users
    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    // Both sections should be present
    await expect(sidebar.getByText("Build", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("Discover", { exact: true })).toBeVisible();
  });

  test("no console errors from navigation rendering", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    // Wait for async operations to settle
    await page.waitForLoadState("networkidle").catch(() => {});

    // Filter out known non-navigation errors (API/network failures)
    const navErrors = consoleErrors.filter(
      (err) =>
        !err.includes("fetch") &&
        !err.includes("ERR_CONNECTION") &&
        !err.includes("NetworkError") &&
        !err.includes("Failed to load") &&
        !err.includes("api/v2") &&
        !err.includes("localhost:8001") &&
        !err.includes("net::") &&
        !err.includes("ECONNREFUSED")
    );

    expect(
      navErrors,
      "No console errors related to navigation rendering"
    ).toEqual([]);
  });

  test("screenshot: full sidebar", async ({ page }) => {
    await page.goto("/solve");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await sidebar.screenshot({
      path: "e2e/screenshots/sidebar-nav-full.png",
    });
  });
});
