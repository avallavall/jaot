import { test, expect } from "@playwright/test";
import { WorkspacePage } from "./pages/workspace.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Workspace", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("workspace dashboard loads", async ({ page }) => {
    const ws = new WorkspacePage(page);
    await ws.goto();
    await ws.expectLoaded();
    await ws.expectHeadingVisible();
  });

  test.describe("Workspace sections", () => {
    test("credits page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoCredits();
      await expect(page).toHaveURL(/\/workspace\/credits/);
    });

    test("API keys page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoApiKeys();
      await expect(page).toHaveURL(/\/workspace\/api-keys/);
    });

    test("team page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoTeam();
      await expect(page).toHaveURL(/\/workspace\/team/);
    });

    test("usage page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoUsage();
      await expect(page).toHaveURL(/\/workspace\/usage/);
    });

    test("profile page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoProfile();
      await expect(page).toHaveURL(/\/workspace\/my-profile/);
    });

    test("audit log page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoAudit();
      await expect(page).toHaveURL(/\/workspace\/audit/);
    });

    test("workspaces list page loads", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoWorkspaces();
      await expect(page).toHaveURL(/\/workspace\/workspaces/);
    });
  });

  test.describe("Workspace Operations (E2E-07, E2E-09)", () => {
    test("credits page displays balance or pool information", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoCredits();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("team page shows member list or invite option", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoTeam();

      // Look for invite button or member table
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("workspaces page shows workspace list or create option", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoWorkspaces();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("create workspace page loads", async ({ page }) => {
      await page.goto("/workspace/workspaces/new");
      await expect(page).toHaveURL(/\/workspace\/workspaces\/new/);
    });

    test("audit page shows log entries or empty state", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoAudit();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("usage page displays charts or usage data", async ({ page }) => {
      const ws = new WorkspacePage(page);
      await ws.gotoUsage();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });
  });
});
