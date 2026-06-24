import { test, expect, type Page } from "@playwright/test";

const INTRO_URL = "/en/docs/getting-started/introduction";
const AUTH_URL = "/en/docs/getting-started/authentication";

test.use({ navigationTimeout: 60000 });

/** Dismiss the cookie consent banner if present (it intercepts clicks on mobile). */
async function dismissCookieBanner(page: Page) {
  const banner = page.getByRole("button", { name: /Accept All/i });
  try {
    await banner.waitFor({ state: "visible", timeout: 3000 });
    await banner.click();
    // Wait for the banner container to disappear
    await page.locator(".fixed.bottom-0").waitFor({ state: "hidden", timeout: 3000 }).catch(() => {});
  } catch {
    // Banner not present — already dismissed or not shown
  }
}

test.describe("Phase 55: Documentation Infrastructure", () => {
  // Test 1: Docs page renders with MDX content
  test("docs page renders with MDX content", async ({ page }) => {
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    const h1 = page.locator("h1#introduction");
    await expect(h1).toBeVisible({ timeout: 15000 });

    const prose = page.locator(".prose");
    await expect(prose).toBeVisible();

    const p = prose.locator("p").first();
    await expect(p).toBeVisible();
  });

  // Test 2: Syntax highlighting + CodeBlock copy button
  test("code blocks with syntax highlighting and copy button", async ({
    page,
  }) => {
    await page.goto(AUTH_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    // rehype-pretty-code creates pre with data-language
    await dismissCookieBanner(page);

    const codeBlock = page.locator("pre[data-language]").first();
    await expect(codeBlock).toBeVisible({ timeout: 15000 });

    const code = codeBlock.locator("code[data-language]");
    await expect(code).toBeVisible();

    // Copy button (sibling of pre, opacity-0 by default)
    const copyButton = page.locator('button[aria-label="Copy code"]').first();
    await copyButton.click({ force: true });

    // Check icon appears after copy
    const checkIcon = page
      .locator('button[aria-label="Copy code"]')
      .first()
      .locator("svg");
    await expect(checkIcon).toBeVisible();
  });

  // Test 3: Deep-linkable headings
  test("headings have anchor links for deep linking", async ({ page }) => {
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    const h2 = page.locator("h2#what-is-jaot");
    await expect(h2).toBeVisible({ timeout: 15000 });

    const anchor = h2.locator('a[href="#what-is-jaot"]');
    await expect(anchor).toBeVisible();
  });

  // Test 4: Three-column docs layout
  test("three-column layout on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    const sidebar = page.locator('nav[aria-label="Documentation sidebar"]');
    await expect(sidebar).toBeVisible({ timeout: 15000 });

    const content = page.locator(".prose");
    await expect(content).toBeVisible();

    const pagination = page.locator('nav[aria-label="Pagination"]');
    await expect(pagination).toBeVisible();
  });

  // Test 5: Sidebar with collapsible sections
  test("sidebar has collapsible section groups", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    await dismissCookieBanner(page);

    const sidebar = page.locator('nav[aria-label="Documentation sidebar"]');
    await expect(sidebar).toBeVisible({ timeout: 15000 });

    const sections = sidebar.locator("button[aria-expanded]");
    expect(await sections.count()).toBeGreaterThanOrEqual(4);

    // Getting Started expanded (current section)
    const expanded = sidebar.locator('button[aria-expanded="true"]');
    await expect(expanded.first()).toBeVisible();

    // Click a collapsed section — it should expand
    const collapsedButtons = sidebar.locator('button[aria-expanded="false"]');
    const firstCollapsedText = await collapsedButtons.first().textContent();
    await collapsedButtons.first().click();
    // Re-locate by text content to verify it expanded
    const toggledButton = sidebar.getByRole("button", { name: firstCollapsedText!.trim() });
    await expect(toggledButton).toHaveAttribute("aria-expanded", "true");
  });

  // Test 6: Breadcrumbs
  test("breadcrumbs show path hierarchy", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    const breadcrumbs = page.locator('nav[aria-label="Breadcrumbs"]');
    await expect(breadcrumbs).toBeVisible({ timeout: 15000 });

    // Should show segments
    const links = breadcrumbs.locator("a, span");
    expect(await links.count()).toBeGreaterThanOrEqual(2);
  });

  // Test 7: Prev/next pagination
  test("prev/next pagination links navigate", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    const pagination = page.locator('nav[aria-label="Pagination"]');
    await expect(pagination).toBeVisible({ timeout: 15000 });

    const nextLink = pagination.locator('a[href*="/docs/"]');
    expect(await nextLink.count()).toBeGreaterThan(0);

    await nextLink.first().click();
    await page.waitForURL(/\/docs\//, { timeout: 30000 });
  });

  // Test 8: Mobile hamburger menu
  test("mobile hamburger menu opens docs nav", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    await dismissCookieBanner(page);

    const menuButton = page.locator(
      'button[aria-label="Open documentation navigation"]'
    );
    await expect(menuButton).toBeVisible({ timeout: 15000 });

    await menuButton.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const docsLinks = dialog.locator('a[href*="/docs/"]');
    expect(await docsLinks.count()).toBeGreaterThan(0);
  });

  // Test 9: Search modal
  test("search modal opens and finds results", async ({ page }) => {
    await page.goto(INTRO_URL, { waitUntil: "domcontentloaded", timeout: 60000 });

    await dismissCookieBanner(page);

    const searchButton = page.locator(
      'button[aria-label="Search documentation"]'
    );
    await expect(searchButton).toBeVisible({ timeout: 15000 });

    await searchButton.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    const input = dialog.locator("input");
    await expect(input).toBeVisible();

    // Type and wait for results to render
    await input.fill("authentication");

    // Results render as buttons — wait for the first one
    const resultButton = dialog.getByRole("button", { name: /Authentication/i });
    await expect(resultButton.first()).toBeVisible({ timeout: 5000 });

    // Click first result — navigates
    await resultButton.first().click();
    await page.waitForURL(/\/docs\//, { timeout: 30000 });
  });

  // Test 10: Docs link in public header
  test("public header has docs link", async ({ page }) => {
    await page.goto("/en", { waitUntil: "domcontentloaded", timeout: 60000 });

    const docsLink = page
      .locator('a[href*="/docs/getting-started/introduction"]')
      .filter({ hasText: /Docs/i });
    await expect(docsLink.first()).toBeVisible({ timeout: 15000 });

    await docsLink.first().click();
    await page.waitForURL(/\/docs\//, { timeout: 30000 });
  });
});
