import { test, expect, type Locator } from "@playwright/test";

/**
 * Verify code blocks in docs have proper text contrast in both light and dark themes.
 * Regression test for: shiki dual-theme CSS variable mapping was missing,
 * causing invisible text (light-on-light) in light mode.
 */

const CODE_SPAN_SELECTOR =
  "[data-rehype-pretty-code-figure] code span[style], .shiki span[style]";
const CODE_BLOCK_SELECTOR =
  "[data-rehype-pretty-code-figure] pre, .shiki";

/** Compute perceived luminance (0 = black, 255 = white) of a locator's text color. */
async function getTextLuminance(locator: Locator): Promise<number> {
  const textColor = await locator.evaluate((el) =>
    window.getComputedStyle(el).color,
  );
  const match = textColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  expect(match, `Expected rgb() color, got: ${textColor}`).not.toBeNull();
  const [r, g, b] = [parseInt(match![1]), parseInt(match![2]), parseInt(match![3])];
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

test.describe("Docs code block contrast", () => {
  const docsPage = "/docs/marketplace/publishing-models";

  test("light mode: code block text is visible (dark on cream)", async ({ page }) => {
    await page.goto(docsPage);
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.documentElement.classList.remove("dark"));

    const codeBlock = page.locator("[data-rehype-pretty-code-figure] pre").first();
    await expect(codeBlock).toBeVisible();
    await codeBlock.screenshot({ path: "e2e/screenshots/code-block-light.png" });

    const span = page.locator("[data-rehype-pretty-code-figure] code span[style]").first();
    await expect(span).toBeVisible();

    const luminance = await getTextLuminance(span);
    expect(luminance).toBeLessThan(180);
  });

  test("dark mode: code block text is visible (light on dark)", async ({ page }) => {
    await page.goto(docsPage);
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.documentElement.classList.add("dark"));

    const codeBlock = page.locator("[data-rehype-pretty-code-figure] pre").first();
    await expect(codeBlock).toBeVisible();
    await codeBlock.screenshot({ path: "e2e/screenshots/code-block-dark.png" });

    const span = page.locator("[data-rehype-pretty-code-figure] code span[style]").first();
    await expect(span).toBeVisible();

    const luminance = await getTextLuminance(span);
    expect(luminance).toBeGreaterThan(100);
  });

  test("light mode: CodeTabs code blocks also have proper contrast", async ({ page }) => {
    await page.goto("/docs/api/solve");
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.documentElement.classList.remove("dark"));

    const shikiPre = page.locator(".shiki").first();
    if ((await shikiPre.count()) === 0) {
      test.skip();
      return;
    }

    await expect(shikiPre).toBeVisible();
    await shikiPre.screenshot({ path: "e2e/screenshots/codetabs-light.png" });

    const span = page.locator(".shiki span[style]").first();
    const luminance = await getTextLuminance(span);
    expect(luminance).toBeLessThan(180);
  });

  test("multiple docs pages: code blocks visible in light mode", async ({ page }) => {
    const pages = [
      "/docs/getting-started/quick-start",
      "/docs/api/solve",
      "/docs/api/models",
      "/docs/guides/production-planning",
    ];

    for (const url of pages) {
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      await page.evaluate(() => document.documentElement.classList.remove("dark"));

      const codeBlocks = page.locator(CODE_BLOCK_SELECTOR);
      if ((await codeBlocks.count()) === 0) continue;

      const firstBlock = codeBlocks.first();
      await expect(firstBlock).toBeVisible();

      const slug = url.replace(/\//g, "_").slice(1);
      await firstBlock.screenshot({ path: `e2e/screenshots/code-${slug}.png` });

      const span = page.locator(CODE_SPAN_SELECTOR).first();
      if ((await span.count()) === 0) continue;

      const luminance = await getTextLuminance(span);
      expect(luminance, `Code text too light on ${url}`).toBeLessThan(180);
    }
  });
});
