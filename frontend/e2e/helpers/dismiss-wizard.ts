/**
 * Dismiss the WelcomeWizard overlay that auto-opens for authenticated users
 * who haven't completed or dismissed the onboarding wizard.
 *
 * The wizard renders a Radix Dialog overlay (`fixed inset-0 z-50 bg-black/50`)
 * that intercepts ALL pointer events, blocking E2E test clicks.
 *
 * Usage — call once per page after navigating to an authenticated route:
 *
 *   import { dismissWelcomeWizard } from "./helpers/dismiss-wizard";
 *
 *   test.beforeEach(async ({ page }) => {
 *     await dismissWelcomeWizard(page);
 *   });
 *
 * Or use the backend-call variant to dismiss the wizard via real API before navigation:
 *
 *   import { interceptGuidanceApi } from "./helpers/dismiss-wizard";
 *
 *   test.beforeEach(async ({ page }) => {
 *     await interceptGuidanceApi(page);   // real PATCH /api/v2/guidance
 *   });
 */
import type { Page } from "@playwright/test";

/**
 * Dismiss the WelcomeWizard by calling the real /api/v2/guidance PATCH endpoint.
 *
 * NOTE: This function name is kept as `interceptGuidanceApi` for backwards compatibility
 * (27+ callers across the e2e suite). It no longer intercepts/mocks the route — it makes
 * a real backend PATCH call (same pattern as global.setup.ts::dismissWizard).
 *
 * Rationale (Phase 11 D-10): mocking /api/v2/guidance via route.fulfill() was an
 * integration boundary violation. The real PATCH persists wizard_dismissed=true in the
 * database so the WelcomeWizard overlay does not re-open during the test.
 *
 * Must be called AFTER auth is set up (storageState must be loaded so the PATCH is
 * authenticated). Call BEFORE navigating to the target page.
 */
export async function interceptGuidanceApi(page: Page): Promise<void> {
  try {
    await page.request.patch("/api/v2/guidance", {
      data: { wizard_dismissed: true, wizard_completed: true, wizard_step: 5 },
    });
    // Non-OK responses are tolerated silently — best-effort dismissal, the
    // wizard will fail any blocking UI assertions on its own if still visible.
  } catch {
    // Endpoint not reachable in some test environments — tolerate silently
    // for the same reason as above.
  }
}

/**
 * If the WelcomeWizard overlay is visible, dismiss it by clicking "Skip".
 *
 * Safe to call even when the wizard isn't showing — it simply returns.
 */
export async function dismissWelcomeWizard(page: Page): Promise<void> {
  // The wizard overlay is a Radix Dialog with a specific class pattern
  const overlay = page.locator(
    '[data-state="open"][aria-hidden="true"].fixed.inset-0.z-50'
  );

  try {
    await overlay.waitFor({ state: "visible", timeout: 2000 });
  } catch {
    // Wizard not present — nothing to dismiss
    return;
  }

  // The wizard has a "Skip" button inside the dialog content
  const skipButton = page.locator(
    '[role="dialog"] button, [role="dialog"] [role="button"]'
  ).filter({ hasText: /skip/i });

  try {
    await skipButton.first().click({ timeout: 3000 });
    // Wait for overlay to disappear
    await overlay.waitFor({ state: "hidden", timeout: 5000 });
  } catch {
    // If skip button isn't found, try pressing Escape as fallback
    // (though the WelcomeWizard blocks Escape — this is a last resort)
  }
}
