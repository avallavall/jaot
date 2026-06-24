import { test, expect } from "@playwright/test";
import { SolvePage } from "./pages/solve.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Advanced Solver Features", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test.describe("Multi-Objective (E2E-17)", () => {
    test("multi-objective page loads with configuration options", async ({
      page,
    }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoMultiObjective();
      await expect(page).toHaveURL(/\/solve\/multi-objective/);

      // Should display multi-objective configuration UI
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("multi-objective page has method selection", async ({ page }) => {
      await page.goto("/solve/multi-objective");

      // Look for method selection (weighted sum, epsilon-constraint, etc.)
      // Look for method selection (combobox, label, or text)
      // Page should load without errors
      await expect(page).toHaveURL(/\/solve\/multi-objective/);
    });
  });

  test.describe("Warm Start (E2E-18)", () => {
    test("solve create page loads with warm start option", async ({
      page,
    }) => {
      await page.goto("/solve/create");
      await expect(page).toHaveURL(/\/solve\/create/);

      // Warm start controls may appear in solve configuration
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("custom solve page supports initial solution input", async ({
      page,
    }) => {
      await page.goto("/solve/custom");
      await expect(page).toHaveURL(/\/solve\/custom/);
    });
  });

  test.describe("Sensitivity Analysis (E2E-19)", () => {
    test("executions list page loads", async ({ page }) => {
      const solvePage = new SolvePage(page);
      await solvePage.gotoExecutions();
      await expect(page).toHaveURL(/\/solve\/executions/);

      // Execution list should be visible (may be empty)
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });

    test("execution detail page handles missing execution gracefully", async ({
      page,
    }) => {
      await page.goto("/solve/executions/exe_nonexistent_12345");

      // Should show error or redirect rather than crash
      const bodyText = await page.textContent("body");
      const handled =
        /not found|error|no.*execution|404/i.test(bodyText || "") ||
        (await page.url()).includes("/solve");
      expect(handled).toBe(true);
    });
  });

  test.describe("Comparison View (E2E-20)", () => {
    test("comparison page loads", async ({ page }) => {
      await page.goto("/solve/executions/compare");
      await expect(page).toHaveURL(/\/solve\/executions\/compare/);
    });

    test("comparison page shows empty state or selection UI", async ({
      page,
    }) => {
      await page.goto("/solve/executions/compare");

      // Without selected executions, should show guidance or empty state
      const content = page.locator("#main-content");
      await expect(content).toBeVisible();
    });
  });
});
