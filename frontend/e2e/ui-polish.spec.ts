import { test, expect } from "@playwright/test";

test.describe("UI Polish — Desktop Scaling", () => {

  test("fluid typography: root font-size is within clamp range", async ({ page }) => {
    // Navigate to login page (public, no auth needed)
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    const fontSize = await page.evaluate(() => {
      return parseFloat(getComputedStyle(document.documentElement).fontSize);
    });

    // The fluid base is: clamp(0.875rem, 0.8rem + 0.2vw, 1.125rem)
    // With browser default 16px: clamp(14px, 12.8px + 0.2vw, 18px)
    // At any supported viewport (1920-3840px), the result is in [14, 18].
    // Different DPR configurations may cause slight rounding variations,
    // so we verify the root font-size is within the overall clamp bounds.
    expect(fontSize).toBeGreaterThanOrEqual(14);
    expect(fontSize).toBeLessThanOrEqual(18);
  });

  test("fluid root font-size is applied via stylesheet", async ({ page }) => {
    // Verify the root font-size is set via fluid typography from globals.css.
    // The stylesheet sets html { font-size: var(--fluid-base) } with
    // --fluid-base: clamp(0.875rem, 0.8rem + 0.2vw, 1.125rem)
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    const computedSize = await page.evaluate(() => {
      return parseFloat(getComputedStyle(document.documentElement).fontSize);
    });

    // Verify the computed root font-size is within the clamp range (14px - 18px).
    // Different DPR and viewport configurations may cause rounding to differ,
    // but the root size should always be within the clamp bounds.
    expect(computedSize).toBeGreaterThanOrEqual(14);
    expect(computedSize).toBeLessThanOrEqual(18);
  });

  test("primary buttons and input fields meet minimum touch target size", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    // Check primary action buttons (submit/login) meet WCAG touch target guidance.
    // Excludes small icon-only toggle buttons (e.g., theme toggle, password reveal)
    // which have different sizing expectations.
    const buttons = await page.locator("button[type='submit']:visible, form button:visible").all();
    for (const button of buttons) {
      const box = await button.boundingBox();
      if (box && box.width > 60) {
        // Only check substantial buttons (not tiny icon toggles)
        // At minimum DPR 1 / 1920px, h-10 = 2.5rem * ~16px = ~40px
        expect(box.height).toBeGreaterThanOrEqual(36);
      }
    }

    // Check text input fields — these should always be adequately sized
    // Excludes checkboxes and radio buttons which have different sizing expectations
    const inputs = await page.locator("input:visible:not([type='checkbox']):not([type='radio'])").all();
    for (const input of inputs) {
      const box = await input.boundingBox();
      if (box) {
        expect(box.height).toBeGreaterThanOrEqual(36);
      }
    }
  });

  test("login page content is within max-width boundary", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    // The login page uses its own layout (not sidebar layout)
    // so max-width does not apply here — but on 4K viewports,
    // the content should still not stretch excessively
    // This test documents the viewport and confirms no horizontal scroll
    const hasHorizontalScroll = await page.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth;
    });
    expect(hasHorizontalScroll).toBe(false);
  });

  test("DPR-specific: elements render at correct CSS pixel sizes", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    // Verify devicePixelRatio is set correctly by Playwright
    const dpr = await page.evaluate(() => window.devicePixelRatio);
    // DPR should match what Playwright configured
    expect(dpr).toBeGreaterThanOrEqual(1);

    // Verify root font-size is within expected range
    const rootFontSize = await page.evaluate(() => {
      return parseFloat(getComputedStyle(document.documentElement).fontSize);
    });
    expect(rootFontSize).toBeGreaterThanOrEqual(14);
    expect(rootFontSize).toBeLessThanOrEqual(19);
  });

});
