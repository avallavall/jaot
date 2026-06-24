import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Accessibility audit using axe-core.
 *
 * Scans key pages for WCAG 2.1 violations.
 * Critical and serious violations fail the test immediately.
 * Minor and moderate violations are logged but allowed (fix later).
 */

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

// ---------------------------------------------------------------------------
// Public pages (no auth required)
// ---------------------------------------------------------------------------
test.describe("Accessibility - Public Pages", () => {
  test("homepage has no critical or serious a11y violations", async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    await assertAccessible(page);
    await context.close();
  });

  test("login page has no critical or serious a11y violations", async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    await assertAccessible(page);
    await context.close();
  });

  test("signup page has no critical or serious a11y violations", async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/signup");
    await page.waitForLoadState("domcontentloaded");

    await assertAccessible(page);
    await context.close();
  });

  test("marketplace page has no critical or serious a11y violations", async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/marketplace");
    await page.waitForLoadState("domcontentloaded");

    await assertAccessible(page);
    await context.close();
  });

  test("pricing page has no critical or serious a11y violations", async ({
    browser,
  }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await page.goto("/pricing");
    await page.waitForLoadState("domcontentloaded");

    await assertAccessible(page);
    await context.close();
  });
});

// ---------------------------------------------------------------------------
// Authenticated pages (uses project-level storageState from "chromium" project)
// ---------------------------------------------------------------------------
test.describe("Accessibility - Authenticated Pages", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("builder page has no critical or serious a11y violations", async ({
    page,
  }) => {
    await page.goto("/builder");
    await page.waitForLoadState("domcontentloaded");

    // Wait for the main content to render (heading or main area)
    await page
      .getByRole("heading")
      .first()
      .waitFor({ state: "visible", timeout: 15_000 });

    await assertAccessible(page);
  });

  test("solve page has no critical or serious a11y violations", async ({
    page,
  }) => {
    await page.goto("/solve");
    await page.waitForLoadState("domcontentloaded");

    // Wait for the solve dashboard to render
    await page
      .getByRole("heading")
      .first()
      .waitFor({ state: "visible", timeout: 15_000 });

    await assertAccessible(page);
  });
});
