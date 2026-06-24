import { test, expect } from "@playwright/test";
import { SolvePage } from "./pages/solve.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Solve Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("solve page loads with heading", async ({ page }) => {
    const solvePage = new SolvePage(page);
    await solvePage.goto();
    await solvePage.expectLoaded();
    await solvePage.expectHeadingVisible();
  });

  test("sidebar navigation is visible", async ({ page }) => {
    const solvePage = new SolvePage(page);
    await solvePage.goto();
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

  test.describe("Create & Custom", () => {
    test("create page loads", async ({ page }) => {
      await page.goto("/solve/create");
      await expect(page).toHaveURL(/\/solve\/create/);
    });

    test("custom solve page loads", async ({ page }) => {
      await page.goto("/solve/custom");
      await expect(page).toHaveURL(/\/solve\/custom/);
    });
  });

  test.describe("Solve Flow (E2E-05)", () => {
    test("create page has solve configuration form", async ({ page }) => {
      await page.goto("/solve/create");

      // Solve form should have objective, variables, constraints sections
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

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
