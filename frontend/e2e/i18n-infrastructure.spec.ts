import { test, expect } from "@playwright/test";

/**
 * Locate the LanguageSwitcher button (dropdown trigger with Globe icon).
 * Uses data-slot attribute to distinguish from Next.js dev tools button.
 */
function langSwitcher(page: import("@playwright/test").Page) {
  return page.locator('[data-slot="dropdown-menu-trigger"]').filter({ has: page.locator("svg") });
}

test.describe("Phase 52: i18n Infrastructure", () => {
  test.describe("Locale Routing", () => {
    test("English homepage serves without locale prefix", async ({ page }) => {
      await page.goto("/");
      await expect(page).toHaveURL(/\/$/);
      await expect(page).toHaveTitle(/JAOT/i);
    });

    test("/en redirects to / (no prefix for default locale)", async ({ page }) => {
      await page.goto("/en");
      await expect(page).not.toHaveURL(/\/en/);
    });

    test("Spanish pages load with /es prefix", async ({ page }) => {
      await page.goto("/es");
      await expect(page).toHaveURL(/\/es/);
      await expect(page).toHaveTitle(/JAOT/i);
    });

    test("French pages load with /fr prefix", async ({ page }) => {
      await page.goto("/fr");
      await expect(page).toHaveURL(/\/fr/);
      await expect(page).toHaveTitle(/JAOT/i);
    });

    test("All 5 locale prefixes are routable", async ({ page }) => {
      const locales = ["es", "ca", "fr", "de"];
      for (const loc of locales) {
        const res = await page.goto(`/${loc}`);
        expect(res?.status(), `/${loc} should return 200`).toBe(200);
      }
    });
  });

  test.describe("hreflang Tags", () => {
    test("Homepage includes hreflang tags for all locales", async ({ page }) => {
      await page.goto("/");
      const hreflangs = await page.locator('link[rel="alternate"][hreflang]').all();
      expect(hreflangs.length).toBeGreaterThanOrEqual(5);
    });

    test("hreflang=en points to root (no prefix)", async ({ page }) => {
      await page.goto("/");
      const enLink = page.locator('link[rel="alternate"][hreflang="en"]');
      const href = await enLink.getAttribute("href");
      expect(href).toBeTruthy();
      expect(href).not.toContain("/en");
    });

    test("hreflang=es points to /es", async ({ page }) => {
      await page.goto("/");
      const esLink = page.locator('link[rel="alternate"][hreflang="es"]');
      const href = await esLink.getAttribute("href");
      expect(href).toContain("/es");
    });
  });

  test.describe("Language Switcher (Public Pages)", () => {
    test("Language switcher is visible on homepage", async ({ page }) => {
      await page.goto("/");
      await expect(langSwitcher(page)).toBeVisible();
      // Should show current locale code
      await expect(langSwitcher(page)).toContainText("en");
    });

    test("Language switcher dropdown shows all 5 languages", async ({ page }) => {
      await page.goto("/");
      await langSwitcher(page).click();

      await expect(page.getByRole("menuitem", { name: "English" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Español" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Français" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Deutsch" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Català" })).toBeVisible();

      const items = await page.getByRole("menuitem").all();
      expect(items.length).toBe(5);
    });

    test("Switching to Spanish navigates to /es and updates switcher", async ({ page }) => {
      await page.goto("/");
      await langSwitcher(page).click();
      await page.getByRole("menuitem", { name: "Español" }).click();

      await expect(page).toHaveURL(/\/es/);
      await expect(langSwitcher(page)).toContainText("es");
    });

    test("Switching language preserves current page path", async ({ page }) => {
      await page.goto("/pricing");
      await expect(page).toHaveURL(/\/pricing/);

      await langSwitcher(page).click();
      await page.getByRole("menuitem", { name: "Français" }).click();

      await expect(page).toHaveURL(/\/fr\/pricing/);
    });

    test("Switching back to English removes locale prefix", async ({ page }) => {
      await page.goto("/es/pricing");
      await expect(page).toHaveURL(/\/es\/pricing/);

      await langSwitcher(page).click();
      await page.getByRole("menuitem", { name: "English" }).click();

      await expect(page).toHaveURL(/\/pricing$/);
      await expect(page).not.toHaveURL(/\/en\//);
    });
  });

  test.describe("Accept-Language Detection", () => {
    test("Accept-Language: es redirects to /es", async ({ browser }) => {
      const context = await browser.newContext({
        locale: "es-ES",
      });
      const page = await context.newPage();
      await page.goto("/");
      await expect(page).toHaveURL(/\/es/);
      await context.close();
    });
  });

  test.describe("NEXT_LOCALE Cookie", () => {
    test("NEXT_LOCALE cookie is set after switching locale", async ({ page, context }) => {
      await page.goto("/");
      await langSwitcher(page).click();
      await page.getByRole("menuitem", { name: "Español" }).click();
      await expect(page).toHaveURL(/\/es/);

      const cookies = await context.cookies();
      const localeCookie = cookies.find((c) => c.name === "NEXT_LOCALE");
      expect(localeCookie).toBeTruthy();
      expect(localeCookie?.value).toBe("es");
    });
  });
});
