/**
 * Feature Audit: 30 features tested against production with screenshots.
 * Focus on hidden/secondary features that are easy to miss.
 *
 * Run: BASE_URL=https://jaot.io E2E_EMAIL=demo@jaot.io E2E_PASSWORD='DemoHexaly2026!' npx playwright test feature-audit.spec.ts --project=chromium
 */
import { test, expect, Page } from "@playwright/test";

const SCREENSHOT_DIR = "e2e/screenshots/feature-audit";

async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: false,
  });
}

async function waitForContent(page: Page, timeout = 10_000) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForLoadState("networkidle", { timeout }).catch(() => {});
  await page.waitForTimeout(1_500);
}

// ===== 1. WORKSPACE DASHBOARD =====
test("01 — workspace dashboard loads with stats", async ({ page }) => {
  await page.goto("/workspace");
  await waitForContent(page);
  await screenshot(page, "01-workspace-dashboard");
  await expect(page.locator("main")).toBeVisible();
});

// ===== 2. NOTIFICATION BELL =====
test("02 — notification bell in header", async ({ page }) => {
  await page.goto("/workspace");
  await waitForContent(page);
  const bell = page.locator('a[href*="notification"]').first();
  if (await bell.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await screenshot(page, "02-notification-bell");
    await bell.click();
    await waitForContent(page, 5_000);
    await screenshot(page, "02b-notifications-page");
  } else {
    await screenshot(page, "02-notification-header");
  }
});

// ===== 3. API KEYS =====
test("03 — API keys page", async ({ page }) => {
  await page.goto("/workspace/api-keys");
  await waitForContent(page);
  await screenshot(page, "03-api-keys-page");
});

// ===== 4. CREDITS & BILLING =====
test("04 — credits page with balance", async ({ page }) => {
  await page.goto("/workspace/credits");
  await waitForContent(page);
  await screenshot(page, "04-credits-billing");
});

// ===== 5. USAGE ANALYTICS =====
test("05 — usage analytics charts", async ({ page }) => {
  await page.goto("/workspace/usage");
  await waitForContent(page);
  await page.waitForTimeout(2_000);
  await screenshot(page, "05-usage-analytics");
});

// ===== 6. AUDIT LOG =====
test("06 — audit log entries", async ({ page }) => {
  await page.goto("/workspace/audit");
  await waitForContent(page);
  await screenshot(page, "06-audit-log");
  const firstEntry = page.locator("table tbody tr, [role='row']").first();
  if (await firstEntry.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await firstEntry.click();
    await page.waitForTimeout(500);
    await screenshot(page, "06b-audit-log-expanded");
  }
});

// ===== 7. TEAM MANAGEMENT =====
test("07 — team page with members", async ({ page }) => {
  await page.goto("/workspace/team");
  await waitForContent(page);
  await screenshot(page, "07-team-management");
});

// ===== 8. WORKSPACE SETTINGS =====
test("08 — workspace settings", async ({ page }) => {
  await page.goto("/workspace/settings");
  await waitForContent(page);
  await screenshot(page, "08-workspace-settings");
});

// ===== 9. MY PROFILE =====
test("09 — my profile page", async ({ page }) => {
  await page.goto("/workspace/my-profile");
  await waitForContent(page);
  await screenshot(page, "09-my-profile");
});

// ===== 10. MARKETPLACE BROWSE + SEARCH =====
test("10 — marketplace browse and search", async ({ page }) => {
  await page.goto("/marketplace");
  await waitForContent(page);
  await screenshot(page, "10-marketplace-browse");
  const search = page.getByPlaceholder(/search|buscar/i).first();
  if (await search.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await search.fill("portfolio");
    await page.waitForTimeout(1_500);
    await screenshot(page, "10b-marketplace-search");
  }
});

// ===== 11. MARKETPLACE DETAIL + ALL TABS =====
test("11 — marketplace model detail tabs", async ({ page }) => {
  await page.goto("/marketplace");
  await waitForContent(page);
  const modelLink = page.locator('a[href*="/marketplace/cat_"]').first();
  if (await modelLink.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await modelLink.click();
    await waitForContent(page);
    await screenshot(page, "11-marketplace-detail");
    const tabs = page.locator('[role="tab"]');
    const count = await tabs.count();
    for (let i = 1; i < Math.min(count, 5); i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
      await screenshot(page, `11-tab-${i}`);
    }
  }
});

// ===== 12. MARKETPLACE REVIEW FORM =====
test("12 — review form toggle", async ({ page }) => {
  await page.goto("/marketplace");
  await waitForContent(page);
  const modelLink = page.locator('a[href*="/marketplace/cat_"]').first();
  if (await modelLink.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await modelLink.click();
    await waitForContent(page);
    const reviewBtn = page.getByRole("button", { name: /review|reseña/i }).first();
    if (await reviewBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await reviewBtn.scrollIntoViewIfNeeded();
      await reviewBtn.click();
      await page.waitForTimeout(500);
      await screenshot(page, "12-review-form-open");
    }
  }
});

// ===== 13. MY MODELS (SOLVE) =====
test("13 — solve page model list", async ({ page }) => {
  await page.goto("/solve");
  await waitForContent(page);
  await screenshot(page, "13-solve-models-list");
});

// ===== 14. FAVORITES =====
test("14 — favorites page", async ({ page }) => {
  await page.goto("/solve/favorites");
  await waitForContent(page);
  await screenshot(page, "14-favorites-page");
});

// ===== 15. SOLVE MODEL INPUT FORM =====
test("15 — solve model input form", async ({ page }) => {
  await page.goto("/solve");
  await waitForContent(page);
  const modelCard = page.locator('a[href*="/solve/mdl_"]').first();
  if (await modelCard.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await modelCard.click();
    await waitForContent(page);
    await screenshot(page, "15-solve-input-form");
  } else {
    await screenshot(page, "15-solve-no-models");
  }
});

// ===== 16. EXECUTION HISTORY =====
test("16 — execution history page", async ({ page }) => {
  await page.goto("/solve");
  await waitForContent(page);
  const modelCard = page.locator('a[href*="/solve/mdl_"]').first();
  if (await modelCard.isVisible({ timeout: 5_000 }).catch(() => false)) {
    const href = await modelCard.getAttribute("href");
    if (href) {
      await page.goto(href + "/history");
      await waitForContent(page);
      await screenshot(page, "16-execution-history");
    }
  }
});

// ===== 17. BUILDER HOME =====
test("17 — builder home with saved models", async ({ page }) => {
  await page.goto("/builder");
  await waitForContent(page);
  await screenshot(page, "17-builder-home");
});

// ===== 18. BUILDER CANVAS =====
test("18 — builder canvas with toolbar", async ({ page }) => {
  await page.goto("/builder/bld_c2c0fa9fef2e6188?workspace_id=wks_c747e44b6ba36076");
  await waitForContent(page);
  await page.waitForTimeout(3_000);
  await screenshot(page, "18-builder-canvas");
});

// ===== 19. BUILDER VERSION HISTORY (THE BUG) =====
test("19 — builder version history dropdown", async ({ page }) => {
  await page.goto("/builder/bld_c2c0fa9fef2e6188?workspace_id=wks_c747e44b6ba36076");
  await waitForContent(page);
  await page.waitForTimeout(3_000);

  // Try to find the History button
  const strategies = [
    () => page.getByRole("button", { name: /history|historial/i }).first(),
    () => page.locator("button").filter({ hasText: /history|historial/i }).first(),
  ];

  let found = false;
  for (const getBtn of strategies) {
    const btn = getBtn();
    if (await btn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await btn.click();
      await page.waitForTimeout(2_000);
      await screenshot(page, "19-version-history-open");
      found = true;

      const dropdown = page.locator('[role="menu"], [data-radix-popper-content-wrapper]');
      if (await dropdown.isVisible({ timeout: 2_000 }).catch(() => false)) {
        await screenshot(page, "19b-version-dropdown-content");
      }
      break;
    }
  }

  if (!found) {
    await screenshot(page, "19-version-history-toolbar-debug");
    // Log visible buttons
    const buttons = page.locator("button");
    const btnCount = await buttons.count();
    const btnTexts: string[] = [];
    for (let i = 0; i < Math.min(btnCount, 20); i++) {
      const txt = await buttons.nth(i).textContent().catch(() => "");
      if (txt?.trim()) btnTexts.push(txt.trim());
    }
    console.log("Visible buttons:", btnTexts);
  }
});

// ===== 20. BUILDER SAVE INDICATOR =====
test("20 — builder save indicator", async ({ page }) => {
  await page.goto("/builder/bld_c2c0fa9fef2e6188?workspace_id=wks_c747e44b6ba36076");
  await waitForContent(page);
  await page.waitForTimeout(3_000);
  await screenshot(page, "20-builder-toolbar");
});

// ===== 21. BUILDER TEMPLATES =====
test("21 — builder templates gallery", async ({ page }) => {
  await page.goto("/builder/templates");
  await waitForContent(page);
  await screenshot(page, "21-builder-templates");
});

// ===== 22. TRIGGERS LIST =====
test("22 — triggers page", async ({ page }) => {
  await page.goto("/triggers");
  await waitForContent(page);
  await screenshot(page, "22-triggers-list");
});

// ===== 23. TRIGGER DETAIL TABS =====
test("23 — trigger detail with tabs", async ({ page }) => {
  await page.goto("/triggers");
  await waitForContent(page);
  const triggerLink = page.locator('a[href*="/triggers/trg_"]').first();
  if (await triggerLink.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await triggerLink.click();
    await waitForContent(page);
    await screenshot(page, "23-trigger-detail");
    const tabs = page.locator('[role="tab"]');
    const count = await tabs.count();
    for (let i = 1; i < Math.min(count, 4); i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
      await screenshot(page, `23-trigger-tab-${i}`);
    }
  } else {
    await screenshot(page, "23-no-triggers");
  }
});


// ===== 25. DOCS SEARCH =====
test("25 — documentation and search", async ({ page }) => {
  await page.goto("/docs");
  await waitForContent(page);
  await screenshot(page, "25-docs-page");
  const searchBtn = page.locator("button").filter({ hasText: /search|buscar|Ctrl|⌘/i }).first();
  if (await searchBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await searchBtn.click();
    await page.waitForTimeout(500);
    await screenshot(page, "25b-docs-search-open");
    const searchInput = page.locator('input[type="search"], input[type="text"], [role="searchbox"]').last();
    if (await searchInput.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await searchInput.fill("API");
      await page.waitForTimeout(1_000);
      await screenshot(page, "25c-docs-search-results");
    }
  }
});

// ===== 26. PRICING PAGE =====
test("26 — pricing page with plans", async ({ page }) => {
  await page.goto("/pricing");
  await waitForContent(page);
  await screenshot(page, "26-pricing-page");
});

// ===== 27. MULTI-OBJECTIVE =====
test("27 — multi-objective solve", async ({ page }) => {
  await page.goto("/solve/multi-objective");
  await waitForContent(page);
  await screenshot(page, "27-multi-objective");
});

// ===== 28. SELLER ANALYTICS =====
test("28 — seller analytics dashboard", async ({ page }) => {
  await page.goto("/workspace/credits/seller-analytics");
  await waitForContent(page);
  await page.waitForTimeout(2_000);
  await screenshot(page, "28-seller-analytics");
});

// ===== 29. SIDEBAR NAVIGATION =====
test("29 — sidebar with all nav items", async ({ page }) => {
  await page.goto("/solve");
  await waitForContent(page);
  await screenshot(page, "29-sidebar-navigation");
});

// ===== 30. LOCALE SWITCHER =====
test("30 — locale switching", async ({ page }) => {
  await page.goto("/marketplace");
  await waitForContent(page);
  await screenshot(page, "30-locale-default");
  const localeSel = page.locator("select, button, [role='combobox']").filter({ hasText: /english|español|en\b|es\b/i }).first();
  if (await localeSel.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await localeSel.click();
    await page.waitForTimeout(500);
    await screenshot(page, "30b-locale-options");
  }
});
