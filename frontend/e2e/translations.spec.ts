import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

/**
 * Multi-Language Translation Verification
 *
 * Tests that all 4 non-English locales render translated content,
 * not English fallback text, and that SEO/i18n plumbing works.
 *
 * The expected words come from the message files. The hero was rewritten in
 * August ("Routes, shifts and budgets,") and this spec kept looking for the old
 * "Build, Use, or Automate" in every language, so it failed on a page that was
 * correctly translated.
 */

const ALL_LOCALES = ["es", "ca", "fr", "de"] as const;

type Messages = { public: { hero: { titleLine1: string }; nav: { signIn: string } } };
function messages(locale: string): Messages {
  const file = path.join(__dirname, "..", "messages", `${locale}.json`);
  return JSON.parse(fs.readFileSync(file, "utf-8")) as Messages;
}

/** Translated "Sign In" nav text for each locale */
const SIGN_IN: Record<string, string> = Object.fromEntries(
  ALL_LOCALES.map((l) => [l, messages(l).public.nav.signIn]),
);

/** Translated hero line 1 for each locale */
const HERO_LINE1: Record<string, string> = Object.fromEntries(
  ALL_LOCALES.map((l) => [l, messages(l).public.hero.titleLine1]),
);

const HERO_LINE1_EN = messages("en").public.hero.titleLine1;

test.describe("Multi-Language Translations", () => {
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

        // English fallback hero should NOT appear
        await expect(page.getByText(HERO_LINE1_EN, { exact: true })).not.toBeVisible();
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
      await page.goto("/es");
      await expect(page).toHaveURL(/\/es/);

      // Open language switcher
      const switcher = page.locator('[data-slot="dropdown-menu-trigger"]').filter({ has: page.locator("svg") });
      await switcher.click();

      // Select French
      await page.getByRole("menuitem", { name: "Français" }).click();
      await expect(page).toHaveURL(/\/fr/);

      // French hero text should appear
      await expect(page.getByText(HERO_LINE1.fr)).toBeVisible();
    });

    test("Switch from German back to English removes prefix", async ({ page }) => {
      await page.goto("/de");
      await expect(page).toHaveURL(/\/de/);

      const switcher = page.locator('[data-slot="dropdown-menu-trigger"]').filter({ has: page.locator("svg") });
      await switcher.click();
      await page.getByRole("menuitem", { name: "English" }).click();

      await expect(page).not.toHaveURL(/\/de/);
      // English hero text should appear
      await expect(page.getByText(HERO_LINE1_EN).first()).toBeVisible();
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
