import { test, expect } from "@playwright/test";

/**
 * Phase 58: Multi-Language Translation Verification
 *
 * Tests that all 4 non-English locales render translated content,
 * not English fallback text, and that SEO/glossary features work.
 */

const ALL_LOCALES = ["es", "ca", "fr", "de"] as const;

/** Expected translated "Sign In" nav text for each locale */
const SIGN_IN: Record<string, string> = {
  es: "Iniciar sesión",
  ca: "Iniciar sessió",
  fr: "Se Connecter",
  de: "Anmelden",
};

/** Expected translated hero line 1 for each locale */
const HERO_LINE1: Record<string, string> = {
  es: "Crea, compra o automatiza",
  ca: "Crea, compra o automatitza",
  fr: "Construis, Achète ou Automatise",
  de: "Erstellen, kaufen oder automatisieren",
};

/** Expected translated "Pricing" nav text for each locale */
const PRICING_NAV: Record<string, string> = {
  es: "Precios",
  ca: "Preus",
  fr: "Tarifs",
  de: "Preise",
};

test.describe("Phase 58: Multi-Language Translations", () => {
  test.describe("Homepage renders translated content for all 4 locales", () => {
    for (const locale of ALL_LOCALES) {
      test(`${locale}: homepage shows translated hero and nav text`, async ({ page }) => {
        await page.goto(`/${locale}`);
        await expect(page).toHaveURL(new RegExp(`/${locale}`));

        // Hero title line 1 should be translated
        const heroText = HERO_LINE1[locale];
        await expect(page.getByText(heroText)).toBeVisible({ timeout: 10_000 });

        // "Sign In" nav link should be translated
        const signInText = SIGN_IN[locale];
        await expect(page.getByRole("link", { name: signInText })).toBeVisible();

        // "Pricing" nav link should be translated (use nav scope to avoid matching headings/footer)
        const pricingText = PRICING_NAV[locale];
        await expect(
          page.getByRole("navigation").first().getByRole("link", { name: pricingText })
        ).toBeVisible();

        // English fallback text should NOT appear
        await expect(page.getByText("Build, Buy, or Automate", { exact: true })).not.toBeVisible();
      });
    }
  });

  test.describe("Pricing page renders translated content for all 4 locales", () => {
    for (const locale of ALL_LOCALES) {
      test(`${locale}: pricing page loads with translated title`, async ({ page }) => {
        await page.goto(`/${locale}/pricing`);
        await expect(page).toHaveURL(new RegExp(`/${locale}/pricing`));

        // Page should have JAOT in title
        await expect(page).toHaveTitle(/JAOT/i);

        // Pricing nav should be translated (not English)
        const pricingText = PRICING_NAV[locale];
        await expect(
          page.getByRole("navigation").first().getByRole("link", { name: pricingText })
        ).toBeVisible({ timeout: 10_000 });
      });
    }
  });

  test.describe("hreflang SEO tags present on locale pages", () => {
    for (const locale of ALL_LOCALES) {
      test(`${locale}: hreflang tags include all 5 locales`, async ({ page }) => {
        await page.goto(`/${locale}`);
        const hreflangs = await page.locator('link[rel="alternate"][hreflang]').all();
        // Should have at least 5 (4 non-English + en) + possibly x-default
        expect(hreflangs.length).toBeGreaterThanOrEqual(5);

        // x-default should exist
        const xDefault = page.locator('link[rel="alternate"][hreflang="x-default"]');
        await expect(xDefault).toHaveCount(1);
      });
    }
  });

  test.describe("Language switcher works from non-English locales", () => {
    test("Switch from Spanish to French preserves page", async ({ page }) => {
      await page.goto("/es/pricing");
      await expect(page).toHaveURL(/\/es\/pricing/);

      // Open language switcher
      const switcher = page.locator('[data-slot="dropdown-menu-trigger"]').filter({ has: page.locator("svg") });
      await switcher.click();

      // Select French
      await page.getByRole("menuitem", { name: "Français" }).click();
      await expect(page).toHaveURL(/\/fr\/pricing/);

      // French pricing nav text should appear
      await expect(
        page.getByRole("navigation").first().getByRole("link", { name: PRICING_NAV.fr })
      ).toBeVisible();
    });

    test("Switch from German back to English removes prefix", async ({ page }) => {
      await page.goto("/de");
      await expect(page).toHaveURL(/\/de/);

      const switcher = page.locator('[data-slot="dropdown-menu-trigger"]').filter({ has: page.locator("svg") });
      await switcher.click();
      await page.getByRole("menuitem", { name: "English" }).click();

      await expect(page).not.toHaveURL(/\/de/);
      // English text should appear
      await expect(page.getByText("Build, Buy, or Automate").first()).toBeVisible();
    });
  });

  test.describe("No English fallback text on translated pages", () => {
    // Spot-check a few locales for common English strings that shouldn't appear
    const spotCheckLocales = ["es", "fr", "de"];
    for (const locale of spotCheckLocales) {
      test(`${locale}: no "Sign In" English fallback on homepage`, async ({ page }) => {
        await page.goto(`/${locale}`);
        await expect(page.getByText(HERO_LINE1[locale])).toBeVisible({ timeout: 10_000 });

        // The exact English "Sign In" should not be present (case-sensitive exact match)
        const signInEn = page.getByText("Sign In", { exact: true });
        const count = await signInEn.count();
        expect(count).toBe(0);
      });
    }
  });

  test.describe("html lang attribute matches locale", () => {
    for (const locale of ALL_LOCALES) {
      test(`${locale}: html lang="${locale}"`, async ({ page }) => {
        await page.goto(`/${locale}`);
        const lang = await page.locator("html").getAttribute("lang");
        expect(lang).toBe(locale);
      });
    }
  });
});
