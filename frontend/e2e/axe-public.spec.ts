// LOCAL GATE ONLY — Playwright E2E not in CI (D-06). Run before deploy vs prod Docker build.

import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/** Impact levels that must cause a test failure. */
const BLOCKING_IMPACTS = ["critical", "serious"] as const;

/**
 * Runs an axe accessibility scan and asserts no critical/serious violations.
 * Returns the full results for debugging.
 */
async function assertAccessible(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const blocking = results.violations.filter((v) =>
    BLOCKING_IMPACTS.includes(v.impact as (typeof BLOCKING_IMPACTS)[number])
  );

  if (blocking.length > 0) {
    const summary = blocking
      .map(
        (v) =>
          `[${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} occurrence${v.nodes.length > 1 ? "s" : ""})`
      )
      .join("\n  ");
    expect(
      blocking,
      `Accessibility violations found:\n  ${summary}`
    ).toHaveLength(0);
  }

  return results;
}

// Public routes to sweep for SC2 axe audit.
// Note: the ONLY public image element is ImageGallery.tsx (migrated in Plan 02);
// all other public images are Lucide SVG icons (decorative, aria-hidden by default).
const PUBLIC_ROUTES = [
  "/",
  "/pricing",
  "/contact",
  "/marketplace",
  "/docs/getting-started/introduction",
];

test.describe("Accessibility - Public Routes (SC2 axe sweep)", () => {
  for (const route of PUBLIC_ROUTES) {
    test(`${route} has no critical or serious a11y violations`, async ({
      browser,
    }) => {
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      await page.goto(route);
      await page.waitForLoadState("domcontentloaded");

      await assertAccessible(page);
      await context.close();
    });
  }
});
