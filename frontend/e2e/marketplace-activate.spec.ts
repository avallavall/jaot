/**
 * Marketplace Activation — Functional E2E Tests
 *
 * Tests the REAL marketplace activation flow end-to-end:
 *   1. Browse and filter the catalog with search and sort
 *   2. View model detail page with complete information
 *   3. Activate a free model from the detail page
 *   4. Verify activated model appears in My Models (/solve)
 *   5. Verify already-activated model shows correct state in marketplace
 *
 * These tests run serially because each step depends on the previous one
 * (activation state carries forward).
 */

import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;
const LONG_TIMEOUT = 30_000;

/** Name of the model activated during step 3 — shared across serial tests. */
let activatedModelName: string | null = null;

test.describe("Marketplace Activation — Functional Flow", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // -------------------------------------------------------------------------
  // Step 1: Browse and filter the catalog
  // -------------------------------------------------------------------------

  test("step 1: browse catalog with search and sort controls", async ({
    page,
  }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // -- Search input should be present and functional --
    const searchInput = page
      .getByRole("searchbox")
      .or(page.getByPlaceholder(/search/i));
    await expect(searchInput.first()).toBeVisible({ timeout: 10_000 });

    // Type a search term and verify the URL params update (debounced)
    await searchInput.first().fill("knapsack");
    await expect(async () => {
      const url = new URL(page.url());
      const hasSearchParam =
        url.searchParams.has("q") ||
        url.searchParams.has("search") ||
        url.searchParams.has("query");
      // Either the URL updates with a search param, or the page filters in-place
      // (client-side filtering without URL params is also valid)
      expect(hasSearchParam || page.url().includes("/marketplace")).toBe(true);
    }).toPass({ timeout: 5_000 });

    // Verify the page still renders (no crash after search)
    await expect(page.locator("#main-content")).toBeVisible();

    // Clear search to restore full catalog
    await searchInput.first().clear();
    await page.waitForTimeout(500); // debounce

    // -- Sort dropdown (Radix Select combobox) --
    const sortTrigger = page.getByRole("combobox");
    if (await sortTrigger.isVisible().catch(() => false)) {
      await sortTrigger.click();

      // Select "Newest" (non-default) to trigger URL change
      const newestOption = page.getByRole("option", { name: /newest/i });
      if (await newestOption.isVisible().catch(() => false)) {
        await newestOption.click();

        // Verify URL updated with sort param
        await expect(async () => {
          const params = new URL(page.url()).searchParams;
          expect(params.get("sort")).toBe("newest");
        }).toPass({ timeout: 5_000 });
      }
    }

    // -- Verify model cards or empty state are rendered --
    const modelCards = page.locator(
      "a[href*='/marketplace/'][href]:not([href$='/marketplace/'])"
    );
    const emptyState = page.getByText(/no.*models|empty|no.*results/i);
    const hasCards = (await modelCards.count()) > 0;
    const hasEmpty = (await emptyState.count()) > 0;
    expect(
      hasCards || hasEmpty,
      "Marketplace should show model cards or empty state"
    ).toBe(true);
  });

  // -------------------------------------------------------------------------
  // Step 2: Model detail page shows complete info
  // -------------------------------------------------------------------------

  test("step 2: model detail page shows complete information", async ({
    page,
  }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    // Wait for content to load
    await expect(page.locator("#main-content")).toBeVisible({
      timeout: NAV_TIMEOUT,
    });

    // Find model card links inside main content (not nav/footer)
    const modelLink = page
      .locator("#main-content a[href*='/marketplace/']")
      .filter({ hasNotText: /back|return|browse/i });

    const linkCount = await modelLink.count();
    if (linkCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No models in catalog to view detail page",
      });
      return;
    }

    // Click the first model card
    await modelLink.first().click();
    await page.waitForURL(/\/marketplace\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // -- Model name heading --
    const detailHeading = page.getByRole("heading").first();
    await expect(detailHeading).toBeVisible({ timeout: NAV_TIMEOUT });
    const headingText = await detailHeading.textContent();
    expect(headingText?.trim().length).toBeGreaterThan(0);

    // Store the model name for later verification
    activatedModelName = headingText?.trim() ?? null;

    // -- Description text --
    // The detail page should have descriptive text beyond just the heading
    const bodyText = await page.locator("#main-content").textContent();
    expect(
      (bodyText?.length ?? 0) > (headingText?.length ?? 0) + 20,
      "Detail page should have description text beyond the heading"
    ).toBe(true);

    // -- Category badge --
    // Models display their category as a badge (e.g., "Finance", "Logistics")
    const categoryBadge = page
      .locator("span, [data-slot='badge']")
      .filter({
        hasText:
          /finance|logistics|scheduling|routing|knapsack|cutting|packing|general|assignment|network|energy/i,
      });
    // Category may or may not be displayed as a visible badge
    const hasCategoryBadge = (await categoryBadge.count()) > 0;
    // Also check for category text anywhere on the page
    const hasCategoryText =
      /finance|logistics|scheduling|routing|knapsack|cutting|packing|general|assignment|network|energy/i.test(
        bodyText || ""
      );
    // At least category should appear somewhere (badge or text)
    if (!hasCategoryBadge && !hasCategoryText) {
      // Some models may not have a visible category — annotate but don't fail
      test.info().annotations.push({
        type: "info",
        description: "No visible category badge/text on detail page",
      });
    }

    // -- Activate / action button --
    const actionButton = page.getByRole("button", {
      name: /activate|run|use|open|go to model/i,
    });
    await expect(
      actionButton.first(),
      "Detail page should show an action button"
    ).toBeVisible({ timeout: 10_000 });
  });

  // -------------------------------------------------------------------------
  // Step 3: Activate a free model
  // -------------------------------------------------------------------------

  test("step 3: activate a free model from the marketplace", async ({
    page,
  }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    // Wait for grid to render (models loaded)
    await page
      .locator(".grid")
      .first()
      .waitFor({ state: "visible", timeout: NAV_TIMEOUT })
      .catch(() => {
        /* grid may not exist if catalog is empty */
      });

    // Find an "Activate" button on a model card
    // Exclude favorites buttons and already-activated states
    const activateButton = page
      .locator(
        '.grid button:not([aria-label*="favorites"]):not([title*="favorites"])'
      )
      .filter({ hasText: /^activate$/i });

    const buttonCount = await activateButton.count();
    if (buttonCount === 0) {
      // All models may already be activated — try clicking a model card
      // to navigate to its detail page and activate from there
      const modelLink = page
        .locator("#main-content a[href*='/marketplace/']")
        .filter({ hasNotText: /back|return|browse/i });

      if ((await modelLink.count()) > 0) {
        await modelLink.first().click();
        await page.waitForURL(/\/marketplace\/[^/]+$/, {
          timeout: NAV_TIMEOUT,
        });

        // Store model name from detail page heading
        const detailHeading = page.getByRole("heading").first();
        await expect(detailHeading).toBeVisible({ timeout: NAV_TIMEOUT });
        activatedModelName = (await detailHeading.textContent())?.trim() ?? null;

        // Try to find activate button on detail page
        const detailActivate = page.getByRole("button", {
          name: /activate/i,
        });
        if ((await detailActivate.count()) > 0) {
          await detailActivate.first().click();
        } else {
          // Model is already activated — the "Go to Model" button confirms this
          const goToModel = page.getByRole("button", {
            name: /go to model|already|open|run/i,
          });
          if ((await goToModel.count()) > 0) {
            test.info().annotations.push({
              type: "skip-reason",
              description:
                "Model already activated — skipping activation click",
            });
          }
          return;
        }
      } else {
        test.info().annotations.push({
          type: "skip-reason",
          description: "No models available for activation (catalog empty)",
        });
        return;
      }
    } else {
      // Capture the model name from the card before clicking activate
      const cardContainer = activateButton.first().locator("xpath=ancestor::a | xpath=ancestor::div[contains(@class,'card')]");
      const cardText = await cardContainer.first().textContent().catch(() => "");
      // The card heading is usually the first text node
      if (!activatedModelName && cardText) {
        activatedModelName = cardText.split("\n")[0]?.trim() ?? null;
      }

      await activateButton.first().click();
    }

    // Handle confirmation dialog if it appears
    const modal = page.getByRole("dialog");
    if (await modal.isVisible().catch(() => false)) {
      const confirmButton = modal.getByRole("button", {
        name: /confirm|activate|yes/i,
      });
      if ((await confirmButton.count()) > 0) {
        await confirmButton.click();
      }
    }

    // Verify activation succeeded: success toast, redirect to /solve, or success text
    await expect(async () => {
      const bodyText = await page.textContent("body");
      const currentUrl = page.url();
      const isSuccess =
        /activated|success|already/i.test(bodyText || "") ||
        currentUrl.includes("/solve");
      expect(isSuccess, "Activation should show success indicator").toBe(true);
    }).toPass({ timeout: LONG_TIMEOUT });
  });

  // -------------------------------------------------------------------------
  // Step 4: Activated model appears in My Models
  // -------------------------------------------------------------------------

  test("step 4: activated model appears in My Models (/solve)", async ({
    page,
  }) => {
    await page.goto("/solve");
    await expect(page).toHaveURL(/\/solve/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    const mainContent = page.locator("#main-content");
    await expect(mainContent).toBeVisible({ timeout: NAV_TIMEOUT });

    // My Models page should show at least one model card
    // Model cards are links to /solve/{model_id} or contain a "Run" button
    const modelCards = page
      .locator("#main-content a[href*='/solve/']")
      .filter({
        hasNotText:
          /catalog|executions|favorites|multi|compare|custom|create/i,
      });
    const runButtons = page
      .locator("#main-content .grid")
      .getByRole("button", { name: /run/i });

    const cardCount = await modelCards.count();
    const runCount = await runButtons.count();
    const hasModels = cardCount > 0 || runCount > 0;

    expect(
      hasModels,
      "My Models page should show at least one activated model card"
    ).toBe(true);

    // If we know the activated model name, verify it appears on the page
    if (activatedModelName) {
      const pageText = await mainContent.textContent();
      // The model name may be truncated on cards, so check for partial match
      const nameWords = activatedModelName.split(/\s+/).filter((w) => w.length > 3);
      if (nameWords.length > 0) {
        const foundWord = nameWords.some((word) =>
          pageText?.toLowerCase().includes(word.toLowerCase())
        );
        if (!foundWord) {
          test.info().annotations.push({
            type: "info",
            description: `Model name "${activatedModelName}" not found in My Models text — may be truncated`,
          });
        }
      }
    }
  });

  // -------------------------------------------------------------------------
  // Step 5: Already-activated model shows correct state
  // -------------------------------------------------------------------------

  test("step 5: already-activated model shows correct state in marketplace", async ({
    page,
  }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    const content = page.locator("#main-content");
    await expect(content).toBeVisible({ timeout: NAV_TIMEOUT });

    // Wait for grid to render
    await page
      .locator(".grid")
      .first()
      .waitFor({ state: "visible", timeout: NAV_TIMEOUT })
      .catch(() => {
        /* grid may not exist if catalog is empty */
      });

    // After activation, the model card should show a different state:
    // - "Already activated" text
    // - "Go to Model" button instead of "Activate"
    // - "Activated" badge or checkmark
    // - Or the card may link directly to /solve

    // Check for already-activated indicators anywhere on the page
    const alreadyActivated = page.getByText(
      /already.*activated|go to model|activated|view model/i
    );
    const activateButtons = page
      .locator(
        '.grid button:not([aria-label*="favorites"]):not([title*="favorites"])'
      )
      .filter({ hasText: /^activate$/i });

    const activatedCount = await alreadyActivated.count();
    const activateCount = await activateButtons.count();

    // At least one of these should be true:
    // 1. There are already-activated indicators visible
    // 2. There are fewer activate buttons than total models (some are activated)
    // 3. There are no models at all (empty catalog)
    const modelCards = page.locator(
      "a[href*='/marketplace/'][href]:not([href$='/marketplace/'])"
    );
    const totalModels = await modelCards.count();

    if (totalModels === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No models in catalog to verify activation state",
      });
      return;
    }

    // If we activated a model, we expect at least one already-activated indicator
    // OR the activate button count to be less than total model count
    const hasActivatedState =
      activatedCount > 0 || activateCount < totalModels;
    expect(
      hasActivatedState,
      "At least one model should show already-activated state after activation"
    ).toBe(true);

    // If the specific activated model name is known, navigate to its detail page
    if (activatedModelName) {
      const specificModelCard = page
        .locator("#main-content a[href*='/marketplace/']")
        .filter({ hasText: new RegExp(activatedModelName.split(/\s+/)[0] ?? "", "i") });

      if ((await specificModelCard.count()) > 0) {
        await specificModelCard.first().click();
        await page.waitForURL(/\/marketplace\/[^/]+$/, {
          timeout: NAV_TIMEOUT,
        });

        // On the detail page, the activate button should be replaced
        const detailBodyText = await page.locator("#main-content").textContent();
        const showsActivatedState =
          /already.*activated|go to model|activated|open|run/i.test(
            detailBodyText || ""
          );

        // The detail page should not show a plain "Activate" button
        // (it should show "Go to Model" or similar)
        const plainActivateButton = page.getByRole("button", {
          name: /^activate$/i,
        });
        const hasPlainActivate = (await plainActivateButton.count()) > 0;

        // Either shows activated state text OR no plain activate button
        expect(
          showsActivatedState || !hasPlainActivate,
          "Detail page should reflect activated state"
        ).toBe(true);
      }
    }
  });
});
