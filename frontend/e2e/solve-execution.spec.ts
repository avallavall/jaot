import { test, expect, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;
const LONG_TIMEOUT = 60_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Navigate to /solve, find the first model card with a "Run" button,
 * and return its model ID extracted from the navigation URL.
 *
 * Returns `null` when no models are available (caller should skip).
 */
async function navigateToFirstModelExecution(page: Page): Promise<string | null> {
  await page.goto("/solve");
  await page.waitForLoadState("domcontentloaded");

  const heading = page.getByRole("heading").first();
  await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

  // Wait for model cards to finish loading (spinner disappears)
  await page.locator(".animate-spin").waitFor({ state: "hidden", timeout: NAV_TIMEOUT }).catch(() => {});

  // Look for a "Run" button inside a model card
  const runButtons = page.getByRole("button", { name: /^Run$/i });
  const count = await runButtons.count();
  if (count === 0) return null;

  // Click the first Run button — navigates to /solve/{modelId}
  await runButtons.first().click();
  await page.waitForURL(/\/solve\/[^/]+$/, { timeout: NAV_TIMEOUT });

  // Extract model ID from URL
  const url = page.url();
  const match = url.match(/\/solve\/([^/?#]+)$/);
  return match ? match[1] : null;
}

/**
 * Navigate directly to a model's execution page.
 */
async function gotoModelPage(page: Page, modelId: string): Promise<void> {
  await page.goto(`/solve/${modelId}`);
  await page.waitForLoadState("domcontentloaded");
  // Wait for the loading spinner to disappear (model data loaded)
  await page.locator(".animate-spin").waitFor({ state: "hidden", timeout: NAV_TIMEOUT }).catch(() => {});
}

/**
 * Wait for the execute button to be re-enabled (execution finished).
 */
async function waitForExecutionComplete(page: Page): Promise<void> {
  // The button shows a Loader2 spinner and text "Solving..." while executing.
  // Wait for it to be enabled again OR for an error/result to appear.
  await expect(
    page.locator(".bg-destructive\\/10, .bg-green-100, .bg-red-100, .bg-yellow-100").first(),
  ).toBeVisible({ timeout: LONG_TIMEOUT });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Model Execution — Functional Tests", () => {
  test.describe.configure({ mode: "serial" });

  /** Shared model ID discovered in the first test, reused by subsequent tests. */
  let sharedModelId: string | null = null;
  /** Execution ID captured after a successful run, used for detail page test. */
  let capturedExecutionId: string | null = null;

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // -----------------------------------------------------------------------
  // 1. Model execution page has complete UI
  // -----------------------------------------------------------------------
  test("execution page shows textarea, run button, and model heading", async ({ page }) => {
    sharedModelId = await navigateToFirstModelExecution(page);

    if (!sharedModelId) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No activated models available — environment has no seeded models",
      });
      test.skip();
      return;
    }

    // Model name in heading (h1)
    const h1 = page.locator("h1");
    await expect(h1).toBeVisible({ timeout: NAV_TIMEOUT });
    const headingText = await h1.textContent();
    expect(headingText!.trim().length).toBeGreaterThan(0);

    // Textarea for JSON input (has font-mono class)
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible();

    // Run button (contains "Run" text, may include mode suffix)
    const runButton = page.getByRole("button", { name: /run/i });
    await expect(runButton.first()).toBeVisible();
    await expect(runButton.first()).toBeEnabled();

    // If "Load Example" button exists, click it and verify textarea is populated
    const loadExampleBtn = page.getByRole("button", { name: /load example/i });
    if (await loadExampleBtn.isVisible().catch(() => false)) {
      // Clear textarea first to confirm Load Example actually populates it
      await textarea.fill("");
      await loadExampleBtn.click();

      const value = await textarea.inputValue();
      expect(value.trim().length).toBeGreaterThan(2);

      // The loaded example should be valid JSON
      expect(() => JSON.parse(value)).not.toThrow();
    }
  });

  // -----------------------------------------------------------------------
  // 2. Execute a model with example input (THE MOST IMPORTANT TEST)
  // -----------------------------------------------------------------------
  test("executes a model with example input and displays results", async ({ page }) => {
    test.setTimeout(LONG_TIMEOUT + 30_000); // Extra buffer for navigation + solve

    if (!sharedModelId) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No model ID available from previous test",
      });
      test.skip();
      return;
    }

    // Intercept the execution API to capture the execution ID for later tests
    let executionIdFromApi: string | null = null;
    await page.route("**/api/v2/models/*/execute", async (route) => {
      const response = await route.fetch();
      const body = await response.json().catch(() => null);
      if (body?.id) {
        executionIdFromApi = body.id;
      }
      await route.fulfill({ response });
    });

    await gotoModelPage(page, sharedModelId);

    // Verify textarea has pre-populated JSON from schema.example_input
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: NAV_TIMEOUT });

    let inputValue = await textarea.inputValue();

    // If textarea is empty, try Load Example
    if (!inputValue.trim() || inputValue.trim() === "{}") {
      const loadExampleBtn = page.getByRole("button", { name: /load example/i });
      if (await loadExampleBtn.isVisible().catch(() => false)) {
        await loadExampleBtn.click();
        inputValue = await textarea.inputValue();
      }
    }

    // Verify we have valid, non-empty JSON
    expect(inputValue.trim().length).toBeGreaterThan(2);
    const parsed = JSON.parse(inputValue);
    expect(typeof parsed).toBe("object");
    expect(Object.keys(parsed).length).toBeGreaterThan(0);

    // Click the Run/Execute button
    const runButton = page.getByRole("button", { name: /run/i });
    await expect(runButton.first()).toBeEnabled();
    await runButton.first().click();

    // Button should show loading state
    await expect(
      page.getByText(/solving|starting/i).first(),
    ).toBeVisible({ timeout: 5_000 }).catch(() => {
      // Button may transition too fast for us to catch the spinner — acceptable
    });

    // Wait for result or error to appear
    await waitForExecutionComplete(page);

    // Check what we got: completed result or graceful error
    const statusBadge = page.locator(
      "span.bg-green-100, span.bg-red-100, span.bg-yellow-100",
    ).first();

    const errorBox = page.locator(".bg-destructive\\/10").first();
    const hasStatusBadge = await statusBadge.isVisible().catch(() => false);
    const hasErrorBox = await errorBox.isVisible().catch(() => false);

    // At least one of them must be visible — the execution completed
    expect(hasStatusBadge || hasErrorBox).toBe(true);

    if (hasStatusBadge) {
      const statusText = (await statusBadge.textContent()) || "";
      // Status should be one of the known statuses
      expect(statusText.trim()).toMatch(/COMPLETED|FAILED|TIMEOUT|INFEASIBLE/i);

      if (/COMPLETED/i.test(statusText)) {
        // -- Objective Value is displayed --
        const objectiveSection = page.locator("text=Objective Value").first();
        await expect(objectiveSection).toBeVisible();

        // The objective value should be a number rendered in the 2xl bold div
        const objectiveValue = page
          .locator(".text-2xl.font-bold")
          .first();
        await expect(objectiveValue).toBeVisible();
        const objText = (await objectiveValue.textContent()) || "";
        // Should contain a numeric value (e.g., "123.4567" or "N/A")
        expect(objText.trim().length).toBeGreaterThan(0);

        // -- Solve Time is displayed --
        const solveTimeLabel = page.locator("text=Solve Time").first();
        await expect(solveTimeLabel).toBeVisible();

        // -- Credits consumed line --
        const creditsLine = page.getByText(/credits consumed/i).first();
        await expect(creditsLine).toBeVisible();

        // Capture execution ID for the detail page test
        capturedExecutionId = executionIdFromApi;
      }
    }

    // If it was an error (e.g., insufficient credits), that's still a valid
    // outcome — the test verifies the system handles it gracefully
    if (hasErrorBox && !hasStatusBadge) {
      const errorText = await errorBox.textContent();
      expect(errorText!.trim().length).toBeGreaterThan(0);
    }
  });

  // -----------------------------------------------------------------------
  // 3. Invalid JSON input shows error
  // -----------------------------------------------------------------------
  test("shows error for invalid JSON input without crashing", async ({ page }) => {
    if (!sharedModelId) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No model ID available",
      });
      test.skip();
      return;
    }

    await gotoModelPage(page, sharedModelId);

    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: NAV_TIMEOUT });

    // Clear and type invalid JSON
    await textarea.fill("{invalid json syntax");

    // Click run
    const runButton = page.getByRole("button", { name: /run/i });
    await runButton.first().click();

    // Error message should appear (the red destructive box)
    const errorBox = page.locator(".bg-destructive\\/10");
    await expect(errorBox.first()).toBeVisible({ timeout: 5_000 });

    const errorText = await errorBox.first().textContent();
    // Should mention JSON syntax issue
    expect(errorText!.toLowerCase()).toMatch(/json|syntax|invalid|parse/i);

    // Page should still be functional — textarea should remain editable
    await expect(textarea).toBeVisible();
    await expect(textarea).toBeEditable();

    // Run button should be enabled again (not stuck in loading)
    await expect(runButton.first()).toBeEnabled();
  });

  // -----------------------------------------------------------------------
  // 4. Empty input shows validation error
  // -----------------------------------------------------------------------
  test("shows validation error for empty input", async ({ page }) => {
    if (!sharedModelId) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No model ID available",
      });
      test.skip();
      return;
    }

    await gotoModelPage(page, sharedModelId);

    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: NAV_TIMEOUT });

    // Set textarea to empty JSON object
    await textarea.fill("{}");

    // Click run
    const runButton = page.getByRole("button", { name: /run/i });
    await runButton.first().click();

    // One of two outcomes:
    // 1. Validation error appears in the red box (missing required fields)
    // 2. The backend returns an error (422 or similar)
    // Either way, something meaningful should happen — not a silent pass
    const errorBox = page.locator(".bg-destructive\\/10");
    const statusBadge = page.locator(
      "span.bg-green-100, span.bg-red-100, span.bg-yellow-100",
    );

    // Wait for either error or result to appear
    await expect(
      errorBox.first().or(statusBadge.first()),
    ).toBeVisible({ timeout: LONG_TIMEOUT });

    const hasError = await errorBox.first().isVisible().catch(() => false);
    const hasStatus = await statusBadge.first().isVisible().catch(() => false);

    if (hasError) {
      const errorText = await errorBox.first().textContent();
      expect(errorText!.trim().length).toBeGreaterThan(0);
      // Error should mention validation, missing field, or similar
      expect(errorText!.toLowerCase()).toMatch(
        /validat|missing|required|error|invalid|field|input/i,
      );
    } else if (hasStatus) {
      // If the model accepts empty input (no required fields), that's valid
      // — verify it shows a real status
      const text = await statusBadge.first().textContent();
      expect(text!.trim()).toMatch(/COMPLETED|FAILED|TIMEOUT|INFEASIBLE/i);
    }

    // Confirm the page is still functional
    await expect(textarea).toBeEditable();
    await expect(runButton.first()).toBeEnabled();
  });

  // -----------------------------------------------------------------------
  // 5. Execution history page shows past runs
  // -----------------------------------------------------------------------
  test("execution history page displays table with entries or empty state", async ({ page }) => {
    await page.goto("/solve/executions");
    await page.waitForLoadState("domcontentloaded");

    // Page heading
    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });
    const headingText = await heading.textContent();
    expect(headingText!.toLowerCase()).toContain("execution");

    // Wait for loading to finish
    await page.locator(".animate-spin").waitFor({ state: "hidden", timeout: NAV_TIMEOUT }).catch(() => {});

    // Status filter should be visible
    const statusFilter = page.locator("select").first();
    await expect(statusFilter).toBeVisible();

    // Check if we have executions in the table
    const tableRows = page.locator("table tbody tr");
    const rowCount = await tableRows.count();

    if (rowCount > 0) {
      // Table has data — verify the first row has meaningful content

      // Status badge (colored pill)
      const firstRowStatus = tableRows.first().locator("span.rounded-full").first();
      await expect(firstRowStatus).toBeVisible();
      const statusText = (await firstRowStatus.textContent()) || "";
      expect(statusText.trim()).toMatch(/completed|failed|running|pending/i);

      // Date column should have a non-empty value
      // The last actionable cell has a "View" button
      const viewButton = tableRows.first().getByRole("button", { name: /view/i });
      await expect(viewButton).toBeVisible();

      // Total executions count should be > 0
      const totalText = page.getByText(/\d+ total executions/i);
      await expect(totalText).toBeVisible();
    } else {
      // Empty state should be shown
      const emptyState = page.getByText(/no executions/i);
      await expect(emptyState.first()).toBeVisible();
    }
  });

  // -----------------------------------------------------------------------
  // 6. Execution detail page shows complete result
  // -----------------------------------------------------------------------
  test("execution detail page displays status, metadata, and result data", async ({ page }) => {
    // Strategy: navigate to executions list and click the first "View" button.
    // If we captured an execution ID from the run test, try that first.
    if (capturedExecutionId) {
      await page.goto(`/solve/executions/${capturedExecutionId}`);
    } else {
      // Fall back to finding one from the executions list
      await page.goto("/solve/executions");
      await page.waitForLoadState("domcontentloaded");
      await page.locator(".animate-spin").waitFor({ state: "hidden", timeout: NAV_TIMEOUT }).catch(() => {});

      const viewButton = page.getByRole("button", { name: /view/i }).first();
      const hasView = await viewButton.isVisible({ timeout: 5_000 }).catch(() => false);

      if (!hasView) {
        test.info().annotations.push({
          type: "skip-reason",
          description: "No executions available to view detail page",
        });
        test.skip();
        return;
      }

      await viewButton.click();
    }

    await page.waitForURL(/\/solve\/executions\//, { timeout: NAV_TIMEOUT });
    await page.waitForLoadState("domcontentloaded");

    // Wait for loading skeleton to disappear
    await page.locator(".animate-pulse").waitFor({ state: "hidden", timeout: NAV_TIMEOUT }).catch(() => {});

    // Check for error state (execution not found)
    const errorState = page.locator(".bg-destructive\\/10").first();
    if (await errorState.isVisible().catch(() => false)) {
      // If the execution was deleted or not found, that's handled gracefully
      const errorText = await errorState.textContent();
      expect(errorText!.trim().length).toBeGreaterThan(0);
      return;
    }

    // -- Status badge --
    const statusBadge = page.locator("span.rounded-full.font-medium").first();
    await expect(statusBadge).toBeVisible({ timeout: NAV_TIMEOUT });
    const statusText = (await statusBadge.textContent()) || "";
    expect(statusText.trim()).toMatch(/completed|failed|running|pending|timeout/i);

    // -- Execution ID displayed (UUID format, no exe_ prefix) --
    const idText = page.getByText(/ID:\s*[0-9a-f\-]{36}/i);
    await expect(idText).toBeVisible();

    // -- Stats grid: Started, Duration, Credits Used, Solver Status --
    const statsGrid = page.locator(".grid.grid-cols-2.md\\:grid-cols-4");
    await expect(statsGrid).toBeVisible();

    // "Started" card (multi-locale)
    const startedLabel = page.getByText(/^(Started|Iniciado|Iniciat|Démarré|Gestartet)$/i);
    await expect(startedLabel).toBeVisible();

    // "Credits Used" card (multi-locale)
    const creditsLabel = page.getByText(/^(Credits Used|Créditos usados|Crèdits usats|Crédits utilisés|Credits verbraucht)$/i);
    await expect(creditsLabel).toBeVisible();

    // "Duration" card (multi-locale)
    const durationLabel = page.getByText(/^(Duration|Duración|Durada|Durée|Dauer)$/i);
    await expect(durationLabel).toBeVisible();

    // "Solver Status" card (multi-locale)
    const solverStatusLabel = page.getByText(/^(Solver Status|Estado del solver|Estat del solver|Statut du solveur|Solver-Status)$/i);
    await expect(solverStatusLabel).toBeVisible();

    // -- If completed, objective value should be displayed --
    if (/completed/i.test(statusText)) {
      const objectiveSection = page.locator(".bg-primary\\/10").first();
      if (await objectiveSection.isVisible().catch(() => false)) {
        const objectiveLabel = page.getByText(/^Objective Value$/i);
        await expect(objectiveLabel).toBeVisible();

        const objectiveValue = objectiveSection.locator(".text-2xl.font-bold");
        const objText = (await objectiveValue.textContent()) || "";
        // Should be a formatted number
        expect(objText.trim().length).toBeGreaterThan(0);
        expect(objText.trim()).not.toBe("-");
      }
    }

    // -- Tabs: Results and Sensitivity --
    const resultsTab = page.getByRole("tab", { name: /results/i });
    await expect(resultsTab).toBeVisible();
    const sensitivityTab = page.getByRole("tab", { name: /sensitivity/i });
    await expect(sensitivityTab).toBeVisible();

    // -- Collapsible raw JSON sections --
    const inputJsonSummary = page.locator("summary").filter({ hasText: /input data/i });
    await expect(inputJsonSummary).toBeVisible();

    // Clicking it should reveal the raw JSON pre block
    await inputJsonSummary.click();
    const jsonPre = page.locator("details[open] pre").first();
    await expect(jsonPre).toBeVisible({ timeout: 3_000 });
    const jsonText = await jsonPre.textContent();
    expect(jsonText!.trim().length).toBeGreaterThan(0);
    // Should be parseable JSON
    expect(() => JSON.parse(jsonText!)).not.toThrow();

    // -- Action buttons --
    const runAgainButton = page.getByRole("button", { name: /run again/i });
    // May not be visible for external executions — check gracefully
    if (await runAgainButton.isVisible().catch(() => false)) {
      await expect(runAgainButton).toBeEnabled();
    }
  });
});
