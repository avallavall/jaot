import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";
import { createBlankProject, seedDraft } from "./helpers/studio-project";

/**
 * Studio → marketplace publish flow (P1.5 fusion, G2 endpoint + G7b UI).
 *
 * Publishing upserts the project's 1:1 listing facet and pins its latest
 * COMMITTED version — the marketplace never sees the working draft, so a
 * never-committed project must be guarded away from the form entirely.
 * The listing id IS the project id, so the success redirect lands on
 * `/marketplace/{projectId}`.
 */

const NAV = 20_000;

test.describe("Studio — publish to marketplace", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
    // Pre-consent cookies: the fixed bottom banner otherwise intercepts clicks
    // on controls near the bottom of the long publish form.
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "jaot_cookie_consent",
        JSON.stringify({ essential: true, analytics: false, timestamp: new Date().toISOString() }),
      );
    });
  });

  test("never-committed project shows the commit-first guard, not the form", async ({
    page,
  }) => {
    // A blank project has a draft but zero committed versions.
    const projectId = await createBlankProject(page);

    await page.goto(`/studio/${projectId}/publish`);
    const cta = page.getByTestId("studio-publish-commit-first");
    await expect(cta).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("studio-publish-form")).toHaveCount(0);

    // The CTA sends the user to the workspace to commit first.
    await cta.click();
    await page.waitForURL(new RegExp(`/studio/${projectId}/build`), { timeout: NAV });
  });

  test("commit → Analyze entry → publish form → marketplace listing → edit mode", async ({
    page,
  }) => {
    const projectId = await createBlankProject(page);
    await seedDraft(page, projectId);
    // Name it via the API (reliable) so the listing is identifiable later; the UI
    // rename path is covered by studio-critical-path.
    const named = await page.request.patch(`/api/v2/projects/${projectId}`, {
      data: { name: "E2E Published Model" },
    });
    await expect(named, `rename failed: ${named.status()}`).toBeOK();

    // Commit v1 through the header UI — publish pins a committed version.
    await page.goto(`/studio/${projectId}/build`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^(commit|confirmar)/i }).click();
    const summaryInput = page.locator("#commit-summary");
    await expect(summaryInput).toBeVisible({ timeout: NAV });
    await summaryInput.fill("v1 — initial model");
    await page.getByRole("button", { name: /save version|guardar versi/i }).click();
    // The dialog closes only on a successful commit.
    await expect(summaryInput).toHaveCount(0, { timeout: NAV });

    // The publish entry lives in the Analyze tab (ADR-006: model I/O in Analyze).
    await page.goto(`/studio/${projectId}/analyze`);
    const entry = page.getByTestId("studio-analyze-publish");
    await expect(entry).toBeVisible({ timeout: NAV });
    await entry.click();
    await page.waitForURL(new RegExp(`/studio/${projectId}/publish`), { timeout: NAV });

    // First-publish form: the display name is prefilled from the project.
    const form = page.getByTestId("studio-publish-form");
    await expect(form).toBeVisible({ timeout: NAV });
    await expect(form.locator("input").first()).toHaveValue("E2E Published Model");
    // The full description is the other required field.
    await form.locator("textarea").first().fill("An E2E-published model. Safe to delete.");

    await page.getByTestId("studio-publish-submit").click();
    // Publishing is deliberate: a confirm dialog guards the submit.
    await page.getByRole("button", { name: "Accept" }).click();

    // Success redirects to the new public listing — its id IS the project id.
    await page.waitForURL(new RegExp(`/marketplace/${projectId}`), { timeout: NAV });
    await expect(
      page.getByRole("heading", { name: "E2E Published Model" }).first(),
    ).toBeVisible({ timeout: NAV });
    // The listing is immediately consumable ("Use in studio" renders for everyone).
    await expect(page.getByTestId("marketplace-use-in-studio")).toBeVisible({ timeout: NAV });

    // Re-opening the publish page now lands in EDIT mode: the submit updates the
    // existing listing (media uploads are enabled only here — the listing exists).
    await page.goto(`/studio/${projectId}/publish`);
    await expect(page.getByTestId("studio-publish-form")).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("studio-publish-submit")).toContainText(
      /update|actualizar/i,
    );
  });

  test("legacy /solve/{id}/publish redirects into the studio workspace", async ({
    page,
  }) => {
    // A REAL project id: with a phantom id the workspace bounces on to /studio,
    // masking the redirect under test (and old bookmarks point at real models).
    const projectId = await createBlankProject(page);
    await page.goto(`/solve/${projectId}/publish`);
    await expect(page).toHaveURL(new RegExp(`/studio/${projectId}/build`), {
      timeout: 15_000,
    });
  });
});
