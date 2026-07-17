import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const NAV_TIMEOUT = 15_000;

// P1.5 fusion: using a marketplace model means seeding a fork ModelProject into
// the studio ("Use in studio") — the legacy activate → /solve flow is retired.
test.describe("Marketplace — Complete Adopter Journey", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("step 1: browse marketplace and find models", async ({ page }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Verify search works
    const searchInput = page.getByRole("searchbox").or(page.getByPlaceholder(/search/i));
    await expect(searchInput.first()).toBeVisible({ timeout: 10_000 });

    // Verify sort control exists (Radix Select — renders as combobox button)
    const sortTrigger = page.getByRole("combobox");
    if (await sortTrigger.isVisible().catch(() => false)) {
      await sortTrigger.click();
      await page.getByRole("option", { name: /newest/i }).click();
      await expect(async () => {
        const params = new URL(page.url()).searchParams;
        expect(params.get("sort")).toBe("newest");
      }).toPass({ timeout: 5_000 });
    }

    // Model cards should be visible (or empty state)
    const modelCards = page.locator("a[href*='/marketplace/'][href]:not([href$='/marketplace/'])");
    const emptyState = page.getByText(/no.*models|empty|no.*results/i);

    const hasCards = (await modelCards.count()) > 0;
    const hasEmpty = (await emptyState.count()) > 0;
    expect(hasCards || hasEmpty, "Should show model cards or empty state").toBe(true);
  });

  test("step 2: view model detail page with full info", async ({ page }) => {
    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);

    // Model card links are inside the main content area, not in the nav/footer
    const modelLink = page.locator("#main-content a[href*='/marketplace/']").filter({
      hasNotText: /back|return|browse/i,
    });
    const linkCount = await modelLink.count();

    if (linkCount === 0) {
      test.info().annotations.push({
        type: "skip-reason",
        description: "No models in catalog",
      });
      return;
    }

    await modelLink.first().click();
    await page.waitForURL(/\/marketplace\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // Detail page elements
    const detailHeading = page.getByRole("heading").first();
    await expect(detailHeading).toBeVisible({ timeout: NAV_TIMEOUT });

    // The single primary action post-fusion: "Use in studio"
    await expect(page.getByTestId("marketplace-use-in-studio")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("step 3: 'Use in studio' seeds a fork ModelProject and opens the workspace", async ({
    page,
  }) => {
    // An official model materializes reliably from its example input.
    await page.goto("/marketplace/official_assortment_planning");
    const useBtn = page.getByTestId("marketplace-use-in-studio");
    await expect(useBtn).toBeVisible({ timeout: NAV_TIMEOUT });
    await useBtn.click();

    await page.waitForURL(/\/studio\/(mp_[A-Za-z0-9]+)\/build/, { timeout: NAV_TIMEOUT });
    await expect(page.getByTestId("studio-name-input")).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  test("step 4: the fork appears in My Models (the studio list)", async ({ page }) => {
    await page.goto("/studio");
    await expect(page).toHaveURL(/\/studio/);

    const card = page.getByTestId("studio-project-card").first();
    await expect(card).toBeVisible({ timeout: NAV_TIMEOUT });
  });

  test("step 5: favoriting in the browse grid lists it on the favorites page", async ({
    page,
  }) => {
    await page.goto("/marketplace");
    // Pick an explicit not-yet-favorited heart so re-runs stay idempotent.
    const heart = page
      .locator('button[aria-label="Add to favorites"], button[aria-label="Añadir a favoritos"]')
      .first();
    await expect(heart).toBeVisible({ timeout: NAV_TIMEOUT });
    // Wait for the POST to land before navigating — an immediate goto aborts
    // the in-flight toggle request and the favorite is silently lost.
    const [favResp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/models/favorites/") && r.request().method() === "POST",
        { timeout: 10_000 },
      ),
      heart.click(),
    ]);
    expect(favResp.ok()).toBeTruthy();

    await page.goto("/solve/favorites");
    const card = page.locator("#main-content").getByRole("button", {
      name: /use in studio|usar en el estudio/i,
    });
    await expect(card.first()).toBeVisible({ timeout: NAV_TIMEOUT });
    // Fused attribution: the author resolves through the listing/project org —
    // never the legacy "Unknown" placeholder.
    await expect(page.locator("#main-content").getByText(/unknown/i)).toHaveCount(0);
  });

  test("step 6: unauthenticated visitor browses and is asked to sign in on detail", async ({
    browser,
  }) => {
    // Fresh context without auth: the marketplace is public.
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/marketplace");
    await expect(page).toHaveURL(/\/marketplace/);
    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    await page.goto("/marketplace/official_assortment_planning");
    // No "Use in studio" without auth — a sign-in CTA renders instead.
    await expect(page.getByTestId("marketplace-use-in-studio")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /sign.*in|log.*in|inicia|connect|anmeld/i }).first(),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });
});
