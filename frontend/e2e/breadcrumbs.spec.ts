import { test, expect } from "@playwright/test";
import { seedBuilderDocument, deleteBuilderDocument } from "./helpers/builder";

/**
 * E2E tests for the auto-generating Breadcrumbs component.
 *
 * Runs against the real authenticated backend (chromium project storageState
 * from global.setup.ts). Auth is provided via the user.json cookie — no API
 * mocking. See plan 11-05 (P11-REFACTOR-10).
 *
 * Covers visibility (hidden on top-level, shown on nested), navigation,
 * ARIA accessibility, and builder canvas regression.
 */

test.describe("Breadcrumbs Visibility", () => {
  // chromium project storageState (user.json) provides auth automatically —
  // no test.use({ storageState }) override needed.

  test("no breadcrumbs on /solve (top-level page)", async ({ page }) => {
    await page.goto("/solve");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).not.toBeVisible();
  });

  test("breadcrumbs visible on /solve/create (nested page)", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible({ timeout: 10_000 });
    await expect(breadcrumbNav.getByText("Solve")).toBeVisible();
    await expect(breadcrumbNav.getByText("Create")).toBeVisible();
  });

  test("no breadcrumbs on /workspace (top-level page)", async ({ page }) => {
    await page.goto("/workspace");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).not.toBeVisible();
  });

  test("breadcrumbs visible on /workspace/profile (nested page)", async ({ page }) => {
    await page.goto("/workspace/profile");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible();
    await expect(breadcrumbNav.getByText("Workspace")).toBeVisible();
    await expect(breadcrumbNav.getByText("Profile")).toBeVisible();
  });

  // Admin pages require special auth mock (requireAdmin flag on ProtectedRoute).
  // The admin layout renders its own sidebar config and needs a full admin auth session.
  // These are tested indirectly through the admin E2E suite.
  test("no breadcrumbs on /admin (top-level page)", async ({ page }) => {
    await page.goto("/admin");
    // Admin requires special auth; if sidebar renders, check no breadcrumbs
    const sidebar = page.locator("aside");
    const sidebarVisible = await sidebar.isVisible().catch(() => false);
    if (sidebarVisible) {
      const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
      await expect(breadcrumbNav).not.toBeVisible();
    } else {
      // Admin auth gate - page didn't fully render, skip assertion
      test.skip();
    }
  });

  test("breadcrumbs visible on /workspace/api-keys (nested page)", async ({ page }) => {
    await page.goto("/workspace/api-keys");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible({ timeout: 10_000 });
    await expect(breadcrumbNav.getByText("Workspace")).toBeVisible();
    await expect(breadcrumbNav.getByText("API Keys")).toBeVisible();
  });

  test("no breadcrumbs on /marketplace (top-level page)", async ({ page }) => {
    await page.goto("/marketplace");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).not.toBeVisible();
  });

  test("no breadcrumbs on /triggers (top-level page)", async ({ page }) => {
    await page.goto("/triggers");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).not.toBeVisible();
  });

  test("breadcrumbs visible on /solve/favorites (nested page)", async ({ page }) => {
    await page.goto("/solve/favorites");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible({ timeout: 10_000 });
    await expect(breadcrumbNav.getByText("Solve")).toBeVisible();
    await expect(breadcrumbNav.getByText("Favorites")).toBeVisible();
  });

  test("breadcrumbs visible on /solve/executions (nested page)", async ({ page }) => {
    await page.goto("/solve/executions");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible({ timeout: 10_000 });
    await expect(breadcrumbNav.getByText("Solve")).toBeVisible();
    await expect(breadcrumbNav.getByText("Executions")).toBeVisible();
  });
});

test.describe("Breadcrumbs Navigation", () => {
  test("clicking breadcrumb link navigates to parent on /solve/create", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await breadcrumbNav.getByRole("link", { name: "Solve" }).click();
    await expect(page).toHaveURL(/\/solve$/);
  });

  test("clicking breadcrumb link navigates to parent on /workspace/profile", async ({ page }) => {
    await page.goto("/workspace/profile");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await breadcrumbNav.getByRole("link", { name: "Workspace" }).click();
    await expect(page).toHaveURL(/\/workspace$/);
  });

  test("clicking breadcrumb link navigates to parent on /solve/favorites", async ({ page }) => {
    await page.goto("/solve/favorites");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await breadcrumbNav.getByRole("link", { name: "Solve" }).click();
    await expect(page).toHaveURL(/\/solve$/);
  });

  test("Home link navigates to /", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await breadcrumbNav.getByRole("link", { name: "Home" }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});

test.describe("Breadcrumbs Accessibility", () => {
  test("nav has aria-label Breadcrumb", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible();
  });

  test("contains ol element for list semantics", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    const ol = breadcrumbNav.locator("ol");
    await expect(ol).toBeVisible();
  });

  test("last item has aria-current=page", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    const currentItem = breadcrumbNav.locator('[aria-current="page"]');
    await expect(currentItem).toBeVisible();
    await expect(currentItem).toHaveText("Create");
  });

  test("separators have aria-hidden=true", async ({ page }) => {
    await page.goto("/solve/create");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    const hiddenSeparators = breadcrumbNav.locator('[aria-hidden="true"]');
    // At least 2 separators (after Home, after Solve)
    expect(await hiddenSeparators.count()).toBeGreaterThanOrEqual(2);
  });
});

test.describe("Builder Canvas Regression", () => {
  test("no breadcrumbs on /builder (top-level, sidebar layout)", async ({ page }) => {
    await page.goto("/builder");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).not.toBeVisible();
  });

  test("breadcrumbs visible on /builder/templates (nested, sidebar layout)", async ({ page }) => {
    await page.goto("/builder/templates");
    await page.waitForSelector("aside", { timeout: 15_000 });
    const breadcrumbNav = page.locator('nav[aria-label="Breadcrumb"]');
    await expect(breadcrumbNav).toBeVisible();
    await expect(breadcrumbNav.getByText("Builder")).toBeVisible();
    await expect(breadcrumbNav.getByText("Templates")).toBeVisible();
  });

  test("/builder/<doc_id> is full-screen canvas (no sidebar)", async ({ page }) => {
    const { id: docId } = await seedBuilderDocument(page, "E2E breadcrumbs canvas regression");

    try {
      await page.goto(`/builder/${docId}`);
      const sidebar = page.locator("aside");
      await expect(sidebar).not.toBeVisible({ timeout: 10_000 });

      // WorkspaceBreadcrumb escape route stays visible on canvas pages; the new Breadcrumbs does not.
      const mainContent = page.locator("#main-content");
      await expect(mainContent).toBeVisible();
    } finally {
      await deleteBuilderDocument(page, docId);
    }
  });
});
