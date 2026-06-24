/**
 * Phase 7.4 / D-08 — V-21: /settings/solvers route is removed.
 *
 * After Plan 08 ships, navigating to /[locale]/settings/solvers must yield
 * a 404 (Next.js notFound page). The settings sidebar must NOT contain a
 * "/settings/solvers" link.
 *
 * NOTE: test.fixme markers removed by Plan 12 — production code shipped in
 * Plan 08 Task 1. E2E assertions run against Docker-built stack in CI.
 */
import { test, expect } from "@playwright/test";

test.describe("Phase 7.4 / D-08 — settings-solvers route removed", () => {
  test(
    "V-21: /en/settings/solvers returns 404 after deletion",
    async ({ page }) => {
      const response = await page.goto("/en/settings/solvers");
      expect(response?.status()).toBe(404);
    },
  );

  test(
    "V-21: settings sidebar does not link to /settings/solvers",
    async ({ page }) => {
      await page.goto("/en/settings");
      const link = page.locator('a[href*="/settings/solvers"]');
      await expect(link).toHaveCount(0);
    },
  );
});
