import { test, expect } from "@playwright/test";

/**
 * Sidebar navigation verification tests.
 *
 * Runs against the real authenticated backend (chromium project storageState
 * from global.setup.ts). Auth is provided via the user.json cookie — no API
 * mocking. See plan 11-05 (P11-REFACTOR-09).
 *
 * Current sidebar structure (post-P1.5 fusion, 2026-07):
 *   MODEL, ANALYZE & SOLVE: My Models, New Model, Templates (the studio covers
 *     canvas/assistant/editor/JModel as Build lenses — no legacy /builder entries)
 *   DISCOVER: Marketplace, Favorites
 *   Bottom bar: EN, help, dark mode, Logout
 */

test.describe("Sidebar Navigation Structure", () => {
  // chromium project storageState (user.json) provides auth automatically —
  // no test.use({ storageState }) override needed.

  test("sidebar renders the Model, Analyze & Solve hub with its 3 items", async ({ page }) => {
    await page.goto("/studio");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    // The single hub replaced the old "Build" section (P1.5 fusion / ADR-006).
    await expect(sidebar.getByText("Model, Analyze & Solve")).toBeVisible();

    // The studio is the one door: canvas/assistant/editor/JModel are Build
    // lenses, so the legacy Visual Builder / AI Assistant entries are gone
    // and Templates points at the studio gallery.
    await expect(sidebar.getByText("My Models")).toBeVisible();
    await expect(sidebar.getByText("New Model")).toBeVisible();
    const templates = sidebar.getByRole("link", { name: "Templates", exact: true });
    await expect(templates).toBeVisible();
    await expect(templates).toHaveAttribute("href", /\/studio\/templates$/);
    await expect(sidebar.getByText("Visual Builder")).not.toBeVisible();
    await expect(sidebar.getByText("AI Assistant")).not.toBeVisible();
  });

  test("sidebar renders Discover section with items", async ({ page }) => {
    await page.goto("/studio");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    // P1.5 fusion: no "Activated Models", no "For Sellers" — marketplace models
    // are forked into the studio; favorites is the only other Discover entry.
    await expect(sidebar.getByText("Discover", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("Marketplace", { exact: true })).toBeVisible();
    await expect(sidebar.getByText("Favorites")).toBeVisible();
  });

  test("sidebar has logout button", async ({ page }) => {
    await page.goto("/studio");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await expect(sidebar.getByText("Logout")).toBeVisible();
  });

  test("sidebar has language selector", async ({ page }) => {
    await page.goto("/studio");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await expect(sidebar.getByText("EN")).toBeVisible();
  });

  test("sidebar renders both the hub and Discover sections", async ({ page }) => {
    // Both sections are visible for regular authenticated users
    await page.goto("/studio");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    // Both sections should be present
    await expect(sidebar.getByText("Model, Analyze & Solve")).toBeVisible();
    await expect(sidebar.getByText("Discover", { exact: true })).toBeVisible();
  });

  test("no console errors from navigation rendering", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto("/studio");

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
    await page.goto("/studio");

    const sidebar = page.locator("aside");
    await expect(sidebar).toBeVisible({ timeout: 15_000 });

    await sidebar.screenshot({
      path: "e2e/screenshots/sidebar-nav-full.png",
    });
  });
});
