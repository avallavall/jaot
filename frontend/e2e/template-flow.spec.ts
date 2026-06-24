import { test, expect, type Page } from "@playwright/test";
import { BuilderPage } from "./pages/builder.page";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * E2E tests for the template/catalog/solve flow.
 *
 * Covers the templates listing page, template detail/form pages,
 * form interaction (load example, validation), solve execution,
 * results drawer, and breadcrumb navigation.
 *
 * Uses the `chromium` project (authenticated user via storageState).
 */

const NAV_TIMEOUT = 15_000;
const SOLVE_TIMEOUT = 30_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wait for the templates grid to finish loading (skeleton placeholders gone). */
async function waitForTemplatesLoaded(page: Page): Promise<void> {
  // Skeletons are rendered while loading; wait until they disappear
  await expect(async () => {
    const skeletons = page.locator(".animate-pulse");
    expect(await skeletons.count()).toBe(0);
  }).toPass({ timeout: NAV_TIMEOUT });
}

/** Navigate to /builder/templates and wait for the page to be ready. */
async function gotoTemplatesPage(page: Page): Promise<void> {
  const builderPage = new BuilderPage(page);
  await builderPage.gotoTemplates();
  await expect(page).toHaveURL(/\/builder\/templates/);
  await waitForTemplatesLoaded(page);
}

/** Return all template cards on the templates listing page. */
function allTemplateCards(page: Page) {
  return page.locator(".grid .border.rounded-lg.cursor-pointer");
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Template Flow", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // =========================================================================
  // 1. Templates page loads and shows cards
  // =========================================================================

  test("templates page loads and shows cards with category, name, and description", async ({
    page,
  }) => {
    await gotoTemplatesPage(page);

    // Page heading
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Subtitle paragraph
    const subtitle = page.locator("p.text-muted-foreground").first();
    await expect(subtitle).toBeVisible();

    // At least one template card should be present (seeded catalog)
    const cards = allTemplateCards(page);
    const cardCount = await cards.count();
    expect(cardCount).toBeGreaterThan(0);

    // Verify the first card has the expected anatomy:
    const card = cards.first();

    // Category badge (rounded-full span with category text)
    const badge = card.locator("span.rounded-full").first();
    await expect(badge).toBeVisible();
    const badgeText = await badge.textContent();
    expect(badgeText?.trim().length).toBeGreaterThan(0);

    // Template name (h3 heading inside card)
    const name = card.locator("h3");
    await expect(name).toBeVisible();
    const nameText = await name.textContent();
    expect(nameText?.trim().length).toBeGreaterThan(0);

    // Description paragraph (may not exist on all cards, but most seeded ones have it)
    const description = card.locator("p.line-clamp-2");
    if ((await description.count()) > 0) {
      const descText = await description.textContent();
      expect(descText?.trim().length).toBeGreaterThan(0);
    }

    // "Use Template" button
    const useButton = card.getByRole("button", { name: /use|template/i });
    await expect(useButton).toBeVisible();
  });

  // =========================================================================
  // 2. Template card navigates to correct detail page (by ID, not name)
  // =========================================================================

  test("template card click navigates to /builder/templates/{id}", async ({ page }) => {
    await gotoTemplatesPage(page);

    const cards = allTemplateCards(page);
    const cardCount = await cards.count();
    expect(cardCount).toBeGreaterThan(0);

    // Click the first card
    await cards.first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // URL should contain the template ID, not a human-readable name with spaces
    const url = page.url();
    const templateIdSegment = url.split("/builder/templates/")[1]?.split("?")[0];
    expect(templateIdSegment).toBeTruthy();
    // Template IDs are machine identifiers (official_*, snake_case) — no spaces
    expect(templateIdSegment).not.toMatch(/\s/);
  });

  // =========================================================================
  // 3. Template detail page loads form
  // =========================================================================

  test("template detail page loads form with input fields", async ({ page }) => {
    await gotoTemplatesPage(page);

    // Navigate to the first template
    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // Wait for loading to finish (skeleton disappears, form appears)
    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // Heading with template display name
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible();
    const headingText = await heading.textContent();
    expect(headingText?.trim().length).toBeGreaterThan(0);

    // Solve / submit button
    const solveButton = form.getByRole("button", { name: /solve/i });
    await expect(solveButton).toBeVisible();

    // Load Example button
    const loadExampleButton = form.getByRole("button", { name: /load example|reload example/i });
    await expect(loadExampleButton).toBeVisible();

    // Clear All button
    const clearButton = form.getByRole("button", { name: /clear all/i });
    await expect(clearButton).toBeVisible();
  });

  // =========================================================================
  // 4. Template form shows scenario description
  // =========================================================================

  test("template form shows scenario description when available", async ({ page }) => {
    await gotoTemplatesPage(page);

    // Navigate to first template detail
    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // The scenario description is rendered inside a Card with CardTitle "Scenario" (i18n key)
    // Not all templates may have a scenario, so check conditionally
    const scenarioCard = page.locator(".lg\\:sticky").first();
    if (await scenarioCard.isVisible().catch(() => false)) {
      // Verify the scenario card has a title and description content
      const scenarioTitle = scenarioCard.locator("h3, [class*='CardTitle']").first();
      await expect(scenarioTitle).toBeVisible();

      const scenarioText = scenarioCard.locator("p.text-muted-foreground");
      await expect(scenarioText).toBeVisible();
      const text = await scenarioText.textContent();
      expect(text?.trim().length).toBeGreaterThan(10);
    }
  });

  // =========================================================================
  // 5. Template form pre-fills with example data
  // =========================================================================

  test("load example button pre-fills form with example data", async ({ page }) => {
    await gotoTemplatesPage(page);

    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // Click "Load Example"
    const loadExampleButton = form.getByRole("button", { name: /load example/i });
    await loadExampleButton.click();

    // After loading example, the button text changes to "Reload Example"
    await expect(
      form.getByRole("button", { name: /reload example/i })
    ).toBeVisible({ timeout: 5_000 });

    // Verify that at least one input field or textarea now has a value,
    // or a JSON/code block is populated in the form
    const inputs = form.locator("input:not([type='hidden']), textarea");
    const inputCount = await inputs.count();

    let anyFilled = false;
    for (let i = 0; i < inputCount; i++) {
      const val = await inputs.nth(i).inputValue().catch(() => "");
      if (val.trim().length > 0) {
        anyFilled = true;
        break;
      }
    }

    // Also check for code/JSON blocks that may represent array/object fields
    const codeBlocks = form.locator("pre, code, [data-testid*='json']");
    const hasCodeContent = (await codeBlocks.count()) > 0;

    expect(
      anyFilled || hasCodeContent,
      "At least one form field should be populated after loading example"
    ).toBe(true);
  });

  // =========================================================================
  // 6. Template form validation — submit empty form
  // =========================================================================

  test("submitting empty form shows validation errors", async ({ page }) => {
    await gotoTemplatesPage(page);

    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // Ensure the form starts empty by clicking "Clear All" first
    const clearButton = form.getByRole("button", { name: /clear all/i });
    await clearButton.click();

    // Submit the empty form
    const solveButton = form.getByRole("button", { name: /solve/i });
    await solveButton.click();

    // Validation errors should appear — look for error text or destructive styling
    // The DynamicFormRenderer sets errors as text with red/destructive styling
    await expect(async () => {
      const errorTexts = page.locator(".text-destructive, [role='alert']");
      expect(await errorTexts.count()).toBeGreaterThan(0);
    }).toPass({ timeout: 5_000 });
  });

  // =========================================================================
  // 7. Template solve succeeds — results drawer opens
  // =========================================================================

  test("template solve succeeds and opens results drawer", async ({ page }) => {
    await gotoTemplatesPage(page);

    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // Load example data
    const loadExampleButton = form.getByRole("button", { name: /load example/i });
    await loadExampleButton.click();
    await expect(
      form.getByRole("button", { name: /reload example/i })
    ).toBeVisible({ timeout: 5_000 });

    // Submit the form (solve)
    const solveButton = form.getByRole("button", { name: /solve/i });
    await solveButton.click();

    // The button should show a loading/solving state
    await expect(
      form.getByRole("button", { name: /solving/i })
    ).toBeVisible({ timeout: 5_000 });

    // Wait for the results drawer to open
    const drawer = page.locator('[role="dialog"][aria-modal="true"]');
    await expect(drawer).toBeVisible({ timeout: SOLVE_TIMEOUT });

    // Results drawer should have a status badge
    const statusBadge = drawer.locator("span").filter({
      hasText: /OPTIMAL|FEASIBLE|INFEASIBLE|UNBOUNDED|TIME LIMIT|ERROR/i,
    });
    await expect(statusBadge.first()).toBeVisible({ timeout: 5_000 });
  });

  // =========================================================================
  // 8. Template solve shows objective value
  // =========================================================================

  test("successful solve shows objective value in results drawer", async ({ page }) => {
    await gotoTemplatesPage(page);

    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // Load example and solve
    await form.getByRole("button", { name: /load example/i }).click();
    await expect(
      form.getByRole("button", { name: /reload example/i })
    ).toBeVisible({ timeout: 5_000 });
    await form.getByRole("button", { name: /solve/i }).click();

    // Wait for results drawer
    const drawer = page.locator('[role="dialog"][aria-modal="true"]');
    await expect(drawer).toBeVisible({ timeout: SOLVE_TIMEOUT });

    // Check for optimal/feasible status (these statuses produce objective value)
    const statusBadge = drawer.locator("span").filter({
      hasText: /OPTIMAL|FEASIBLE/i,
    });

    if (await statusBadge.first().isVisible().catch(() => false)) {
      // Objective value section should be present
      const objectiveSection = drawer.locator(".bg-muted.rounded-lg").first();
      await expect(objectiveSection).toBeVisible({ timeout: 5_000 });

      // Should contain a numeric value (formatted with toFixed(4))
      const objectiveValue = objectiveSection.locator(".tabular-nums.font-bold");
      await expect(objectiveValue).toBeVisible();
      const valueText = await objectiveValue.textContent();
      expect(valueText?.trim()).toMatch(/[\d.]+/);

      // Performance metrics should also be visible
      const solveTimeLabel = drawer.getByText(/solve time|ms/i);
      await expect(solveTimeLabel.first()).toBeVisible();

      const creditsLabel = drawer.getByText(/credits/i);
      await expect(creditsLabel.first()).toBeVisible();
    } else {
      // Non-optimal result — verify status explanation is shown
      const statusExplanation = drawer.locator(".rounded-md.border");
      expect(await statusExplanation.count()).toBeGreaterThan(0);
    }
  });

  // =========================================================================
  // 9. Breadcrumb navigation on templates page
  // =========================================================================

  test("templates page shows breadcrumb navigation", async ({ page }) => {
    await gotoTemplatesPage(page);

    // The templates page has custom inline breadcrumbs: Builder / Templates
    // Builder is a clickable button, Templates is a span
    const breadcrumbArea = page.locator(".flex.items-center.gap-2.mb-1");
    await expect(breadcrumbArea).toBeVisible({ timeout: NAV_TIMEOUT });

    // "Builder" link/button should be clickable
    const builderCrumb = breadcrumbArea.locator("button").filter({
      hasText: /builder|constructor/i,
    });
    await expect(builderCrumb).toBeVisible();

    // Separator slash
    const separator = breadcrumbArea.locator("span.text-muted-foreground").filter({
      hasText: "/",
    });
    await expect(separator).toBeVisible();

    // "Templates" label
    const templatesCrumb = breadcrumbArea.locator("span.font-medium");
    await expect(templatesCrumb).toBeVisible();

    // Clicking "Builder" navigates back to /builder
    await builderCrumb.click();
    await page.waitForURL(/\/builder$/, { timeout: NAV_TIMEOUT });
  });

  // =========================================================================
  // 10. Multiple template types work
  // =========================================================================

  test("at least two different templates load correctly", async ({ page }) => {
    await gotoTemplatesPage(page);

    const cards = allTemplateCards(page);
    const cardCount = await cards.count();
    expect(cardCount).toBeGreaterThanOrEqual(2);

    // Collect first two template names and their URLs
    const templatesInfo: { name: string; url: string }[] = [];

    for (let i = 0; i < Math.min(2, cardCount); i++) {
      // Navigate to templates page fresh each time (or go back)
      if (i > 0) {
        await gotoTemplatesPage(page);
      }

      const card = allTemplateCards(page).nth(i);
      const cardName = await card.locator("h3").textContent();

      await card.click();
      await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

      const url = page.url();

      // Wait for the form to load
      const form = page.locator("form");
      await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

      // Verify heading
      const heading = page.getByRole("heading", { level: 1 });
      await expect(heading).toBeVisible();

      // Verify solve button exists
      const solveButton = form.getByRole("button", { name: /solve/i });
      await expect(solveButton).toBeVisible();

      // Verify load example button exists
      const loadExample = form.getByRole("button", { name: /load example|reload example/i });
      await expect(loadExample).toBeVisible();

      templatesInfo.push({
        name: cardName?.trim() ?? "",
        url,
      });
    }

    // The two templates should have different URLs (different template IDs)
    expect(templatesInfo[0].url).not.toBe(templatesInfo[1].url);
  });

  // =========================================================================
  // Bonus: Use Template button on card also navigates
  // =========================================================================

  test("'Use Template' button on card navigates to detail page", async ({ page }) => {
    await gotoTemplatesPage(page);

    const cards = allTemplateCards(page);
    const cardCount = await cards.count();
    expect(cardCount).toBeGreaterThan(0);

    // Click the "Use Template" button (not the card itself)
    const useButton = cards.first().getByRole("button", { name: /use|template/i });
    await expect(useButton).toBeVisible();
    await useButton.click();

    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // Form should load
    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  // =========================================================================
  // Bonus: Results drawer can be closed
  // =========================================================================

  test("results drawer can be closed after solve", async ({ page }) => {
    await gotoTemplatesPage(page);

    await allTemplateCards(page).first().click();
    await page.waitForURL(/\/builder\/templates\/[^/]+$/, { timeout: NAV_TIMEOUT });

    const form = page.locator("form");
    await expect(form).toBeVisible({ timeout: NAV_TIMEOUT });

    // Load example and solve
    await form.getByRole("button", { name: /load example/i }).click();
    await expect(
      form.getByRole("button", { name: /reload example/i })
    ).toBeVisible({ timeout: 5_000 });
    await form.getByRole("button", { name: /solve/i }).click();

    // Wait for results drawer
    const drawer = page.locator('[role="dialog"][aria-modal="true"]');
    await expect(drawer).toBeVisible({ timeout: SOLVE_TIMEOUT });

    // Close via the Close button at the bottom of the drawer
    const closeButton = drawer.getByRole("button", { name: /close/i });
    await closeButton.click();

    // Drawer should disappear
    await expect(drawer).not.toBeVisible({ timeout: 5_000 });

    // The form should still be visible (we're back to the template detail)
    await expect(form).toBeVisible();
  });

  // =========================================================================
  // Bonus: Template detail handles invalid ID gracefully
  // =========================================================================

  test("navigating to a nonexistent template shows error state", async ({ page }) => {
    await page.goto("/builder/templates/nonexistent_template_12345");
    await expect(page).toHaveURL(/\/builder\/templates\/nonexistent_template_12345/);

    // Should show the error state (destructive background)
    const errorBox = page.locator(".bg-destructive\\/10");
    await expect(errorBox).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  // =========================================================================
  // Bonus: Multiple cards show distinct categories
  // =========================================================================

  test("template cards show different categories across the catalog", async ({ page }) => {
    await gotoTemplatesPage(page);

    const cards = allTemplateCards(page);
    const cardCount = await cards.count();

    if (cardCount < 3) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "Need at least 3 templates to verify category diversity",
      });
      return;
    }

    // Collect category badges from all visible cards
    const categories = new Set<string>();
    const limit = Math.min(cardCount, 10);
    for (let i = 0; i < limit; i++) {
      const badge = cards.nth(i).locator("span.rounded-full").first();
      const text = await badge.textContent();
      if (text?.trim()) {
        categories.add(text.trim());
      }
    }

    // With a well-seeded catalog, there should be multiple categories
    expect(categories.size).toBeGreaterThanOrEqual(2);
  });
});
