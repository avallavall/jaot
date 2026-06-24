// Asserts the Plausible tracker is present on public pages. Negative-case
// coverage (tracker MUST NOT load on logged-in surfaces) requires admin
// storage state and is deferred to a follow-up spec.
import { test, expect } from "@playwright/test";

test.describe("Plausible tracker integration", () => {
  test("public /pricing page includes the Plausible tracker script", async ({ page }) => {
    await page.goto("/pricing");
    const tracker = page.locator(
      'script[src="https://plausible.jaot.io/js/script.js"]'
    );
    await expect(tracker).toHaveCount(1);
    await expect(tracker).toHaveAttribute("data-domain", "jaot.io");
  });
});
