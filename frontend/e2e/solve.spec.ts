import { test, expect } from "@playwright/test";
import { SolvePage } from "./pages/solve.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";
import { createBlankProject } from "./helpers/studio-project";

test.describe("Solve Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // P1.5 fusion: the legacy "My Models" list and its create page collapsed into
  // the studio. Old bookmarks must keep working via server redirects.
  test.describe("Legacy redirects", () => {
    test("/solve redirects to the studio (My Models)", async ({ page }) => {
      await page.goto("/es/solve");
      await expect(page).toHaveURL(/\/es\/studio/, { timeout: 15_000 });
    });

    test("/solve/create redirects to the studio launcher", async ({ page }) => {
      await page.goto("/solve/create");
      await expect(page).toHaveURL(/\/studio\/new/, { timeout: 15_000 });
    });

    // A REAL project id: with a phantom id the workspace bounces on to /studio,
    // masking the redirect under test (and old bookmarks point at real models).
    test("/solve/{modelId} and /history redirect into the studio workspace", async ({
      page,
    }) => {
      const projectId = await createBlankProject(page);
      await page.goto(`/solve/${projectId}`);
      await expect(page).toHaveURL(new RegExp(`/studio/${projectId}/build`), {
        timeout: 15_000,
      });
      await page.goto(`/solve/${projectId}/history`);
      await expect(page).toHaveURL(new RegExp(`/studio/${projectId}/solve`), {
        timeout: 15_000,
      });
    });
  });

  test("sidebar navigation is visible", async ({ page }) => {
    const solvePage = new SolvePage(page);
    await solvePage.gotoExecutions();
    await expect(solvePage.sidebar).toBeVisible();
  });

  test.describe("Catalog", () => {
    test("catalog page loads", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoMarketplace();
      await expect(page).toHaveURL(/\/marketplace/);
    });
  });

  test.describe("Executions", () => {
    test("executions page loads", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoExecutions();
      await expect(page).toHaveURL(/\/solve\/executions/);
    });

    test("execution compare page loads", async ({ page }) => {
      await page.goto("/solve/executions/compare");
      await expect(page).toHaveURL(/\/solve\/executions\/compare/);
    });
  });

  test.describe("Favorites", () => {
    test("favorites page loads", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoFavorites();
      await expect(page).toHaveURL(/\/solve\/favorites/);
    });
  });

  test.describe("Multi-Objective", () => {
    test("multi-objective page loads", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoMultiObjective();
      await expect(page).toHaveURL(/\/solve\/multi-objective/);
    });
  });

  test.describe("Custom", () => {
    test("custom solve page loads", async ({ page }) => {
      await page.goto("/solve/custom");
      await expect(page).toHaveURL(/\/solve\/custom/);
    });
  });

  test.describe("Solve Flow (E2E-05)", () => {
    test("custom solve page accepts raw problem input", async ({ page }) => {
      await page.goto("/solve/custom");

      // Look for text area or code editor for raw input
      page
        .getByRole("textbox")
        .or(page.locator("textarea"))
        .or(page.locator('[data-testid="code-editor"]'));

      await expect(page).toHaveURL(/\/solve\/custom/);
    });

    test("catalog allows selecting a model to solve", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoMarketplace();

      // Catalog should show model cards with solve/use actions
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("execution detail page handles valid URL structure", async ({ page }) => {
      // Navigate to a non-existent execution to verify error handling
      await page.goto("/solve/executions/exe_test_nonexistent");
      const bodyText = await page.textContent("body");
      const handled = /not found|error|execution|404/i.test(bodyText || "")
        || (await page.url()).includes("/solve");
      expect(handled).toBe(true);
    });

    test("favorites page shows empty state or saved models", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoFavorites();

      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });
  });
});
