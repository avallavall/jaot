import { test, expect } from "@playwright/test";

// SC4: Per-locale <title> localization for /terms × 5 locales.
// (/terms replaced /pricing — the pricing page died with ADR-008; terms is a
// static public page whose title differs in every locale, which assertion 2 needs.)
// SC3 cross-check: og:title present + non-empty per locale.
// Expected title values sourced from messages/{locale}.json metadata.terms.title.
const LOCALES = ["en", "es", "ca", "fr", "de"] as const;

// BASE_URL must match the site URL used at build time (NEXT_PUBLIC_SITE_URL).
// Playwright's baseURL is for page.goto() only; absolute-URL assertions use this constant.
const BASE_URL = process.env.BASE_URL || "https://jaot.io";

// Inline helpers — test-local copies, not imported from app code (keeps the spec self-contained).
// Contract: "as-needed" locale prefix — "en" gets no prefix; all others get /{locale}.
function localizedPath(pagePath: string, locale: string): string {
  if (locale === "en") return pagePath;
  return `/${locale}${pagePath === "/" ? "" : pagePath}`;
}

// Suppress unused-variable warning: BASE_URL is used as the canonical base for future assertions.
void BASE_URL;

// SC4: Expected metadata.terms.title values per locale.
// Keys sourced directly from frontend/messages/{locale}.json → metadata.terms.title.
// These values are the ground truth: if the page renders any other string, the test fails.
const EXPECTED_TERMS_TITLES: Record<(typeof LOCALES)[number], string> = {
  en: "Terms of Service - JAOT",
  es: "Términos de servicio - JAOT",
  ca: "Termes de servei - JAOT",
  fr: "Conditions d'Utilisation - JAOT",
  de: "Nutzungsbedingungen - JAOT",
};

// D-12: CI build only — runs against prod Docker build (target: runner), NOT npm run dev.
// No auth setup, no mocking — hits real SSR'd HTML (per integration_proof.md Phase 11 policy).
test.describe("SEO per-locale <title> localization", () => {
  for (const locale of LOCALES) {
    test(`terms <title> is localized for ${locale}`, async ({ page }) => {
      const navPath = localizedPath("/terms", locale);
      await page.goto(navPath);

      // SC4 assertion 1: <title> equals the locale's metadata.terms.title exactly.
      const title = await page.title();
      expect(title).toBe(EXPECTED_TERMS_TITLES[locale]);

      // SC4 assertion 2: non-en locales must NOT fall back to the English title.
      // This catches silent i18n fallback where next-intl serves "en" content for
      // missing translations instead of throwing a MISSING_MESSAGE error.
      if (locale !== "en") {
        expect(title).not.toBe(EXPECTED_TERMS_TITLES["en"]);
      }

      // SC3 cross-check: og:title meta tag is present and non-empty.
      // buildPageMetadata always sets openGraph.title (D-07 pitfall 2 fix) — verify it
      // survived SSR and appears in the rendered <head>.
      const ogTitle = await page
        .locator('meta[property="og:title"]')
        .getAttribute("content");
      expect(ogTitle).toBeTruthy();
      expect(typeof ogTitle === "string" && ogTitle.length > 0).toBe(true);
    });
  }
});
