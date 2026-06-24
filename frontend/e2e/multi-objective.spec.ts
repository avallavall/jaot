import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * E2E tests for the Multi-Objective Optimization page.
 *
 * Tests run against the live frontend (Docker at localhost:3000).
 * Uses data-testid and accessible locators for robustness across locales.
 */

test.describe("Multi-Objective Optimization", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
    await page.goto("/solve/multi-objective");
    // Wait for the page to fully hydrate
    await expect(page).toHaveURL(/\/solve\/multi-objective/);
    await expect(
      page.getByRole("heading", {
        name: /multi-objective|multiobjectiu|multiobjetivo|mehrziel|multi-objectif/i,
      })
    ).toBeVisible();
  });

  test("page loads with heading and problem definition", async ({ page }) => {
    // Heading is verified in beforeEach; check Problem Definition section
    await expect(
      page.getByRole("heading", {
        name: /problem definition|definici|définition|problemdefinition/i,
      })
    ).toBeVisible();
  });

  test("form has default variables x and y", async ({ page }) => {
    const varNameInputs = page.getByRole("textbox", { name: "name" });
    await expect(varNameInputs).toHaveCount(2);
    await expect(varNameInputs.nth(0)).toHaveValue("x");
    await expect(varNameInputs.nth(1)).toHaveValue("y");
  });

  test("form has two objective expression inputs", async ({ page }) => {
    const expr0 = page.getByTestId("objective-expression-0");
    const expr1 = page.getByTestId("objective-expression-1");

    await expect(expr0).toBeVisible();
    await expect(expr1).toBeVisible();
  });

  test("can type in objective expressions", async ({ page }) => {
    const expr0 = page.getByTestId("objective-expression-0");
    const expr1 = page.getByTestId("objective-expression-1");

    await expr0.fill("50*x + 40*y");
    await expr1.fill("2*x + 3*y");

    await expect(expr0).toHaveValue("50*x + 40*y");
    await expect(expr1).toHaveValue("2*x + 3*y");
  });

  test("solve button is disabled when expressions are empty", async ({ page }) => {
    const solveBtn = page.getByTestId("solve-btn");
    await expect(solveBtn).toBeVisible();
    await expect(solveBtn).toBeDisabled();
  });

  test("solve button enables after filling expressions", async ({ page }) => {
    const solveBtn = page.getByTestId("solve-btn");
    await expect(solveBtn).toBeDisabled();

    // Fill both objective expressions
    await page.getByTestId("objective-expression-0").fill("50*x + 40*y");
    await page.getByTestId("objective-expression-1").fill("2*x + 3*y");

    await expect(solveBtn).toBeEnabled();
  });

  test("can switch between epsilon and weighted methods", async ({ page }) => {
    const epsilonBtn = page.getByRole("button", { name: /epsilon/i });
    const weightedBtn = page.getByRole("button", {
      name: /weighted|ponder|combinaci/i,
    });

    await expect(epsilonBtn).toBeVisible();
    await expect(weightedBtn).toBeVisible();

    // Switch to weighted mode — weight sliders should appear
    await weightedBtn.click();

    const sliderCount = await page.locator('input[type="range"]').count();
    expect(sliderCount).toBeGreaterThanOrEqual(2);

    // Switch back to epsilon mode
    await epsilonBtn.click();

    await expect(page.locator('input[type="range"]')).toHaveCount(1);
  });

  test("can add a variable", async ({ page }) => {
    const addVarBtn = page.getByTestId("add-variable-btn");
    await expect(addVarBtn).toBeVisible();

    const varNameInputs = page.getByRole("textbox", { name: "name" });
    await expect(varNameInputs).toHaveCount(2);

    await addVarBtn.click();

    await expect(varNameInputs).toHaveCount(3);
  });

  test("can add a constraint", async ({ page }) => {
    const addConstraintBtn = page.getByTestId("add-constraint-btn");
    await expect(addConstraintBtn).toBeVisible();

    const constraintPlaceholder = page.getByPlaceholder(/x \+ y/);
    await expect(constraintPlaceholder).toHaveCount(1);

    await addConstraintBtn.click();

    await expect(constraintPlaceholder).toHaveCount(2);
  });

  test("has objective configuration section with mode toggle", async ({ page }) => {
    await expect(
      page.getByRole("heading", {
        name: /objective configuration|configuraci.*objetivos|configuration.*objectifs|zielkonfiguration/i,
      })
    ).toBeVisible();

    await expect(
      page.getByRole("heading", {
        name: /objective 1|objectiu 1|objetivo 1|objectif 1|ziel 1/i,
      })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /objective 2|objectiu 2|objetivo 2|objectif 2|ziel 2/i,
      })
    ).toBeVisible();

    await expect(page.getByRole("button", { name: /epsilon/i })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /weighted|ponder|combinaci/i })
    ).toBeVisible();
  });

  test("objective labels can be edited", async ({ page }) => {
    const label0 = page.getByTestId("objective-label-0");
    const label1 = page.getByTestId("objective-label-1");

    await expect(label0).toBeVisible();
    await expect(label1).toBeVisible();

    await label0.fill("Revenue");
    await expect(label0).toHaveValue("Revenue");
  });

  test("import source panel is visible with tabs", async ({ page }) => {
    await expect(
      page.getByRole("heading", {
        name: /import source|importar origen|importar font|importer.*source|quelle importieren/i,
      })
    ).toBeVisible();

    await expect(page.getByTestId("import-search")).toBeVisible();
  });
});
