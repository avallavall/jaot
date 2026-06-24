import { test, expect } from "@playwright/test";

// SC4: Per-locale <title> localization for /pricing × 5 locales.
// SC3 cross-check: og:title present + non-empty per locale.
// Expected title values sourced from messages/{locale}.json metadata.pricing.title.
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

// SC4: Expected metadata.pricing.title values per locale.
// Keys sourced directly from frontend/messages/{locale}.json → metadata.pricing.title.
// These values are the ground truth: if the page renders any other string, the test fails.
const EXPECTED_PRICING_TITLES: Record<(typeof LOCALES)[number], string> = {
  en: "Pricing and Plans - JAOT | AI Optimization Platform and Marketplace",
  es: "Precios - JAOT | Planes de la plataforma de optimización",
  ca: "Preus - JAOT | Plans de la plataforma d'optimització",
  fr: "Tarifs - JAOT | Plans de la Plateforme d'Optimisation",
  de: "Preise - JAOT | Pläne für die Optimierungsplattform",
};

// D-12: CI build only — runs against prod Docker build (target: runner), NOT npm run dev.
// No auth setup, no mocking — hits real SSR'd HTML (per integration_proof.md Phase 11 policy).
test.describe("SEO per-locale <title> localization", () => {
  for (const locale of LOCALES) {
    test(`pricing <title> is localized for ${locale}`, async ({ page }) => {
      const navPath = localizedPath("/pricing", locale);
      await page.goto(navPath);

      // SC4 assertion 1: <title> equals the locale's metadata.pricing.title exactly.
      const title = await page.title();
      expect(title).toBe(EXPECTED_PRICING_TITLES[locale]);

      // SC4 assertion 2: non-en locales must NOT fall back to the English title.
      // This catches silent i18n fallback where next-intl serves "en" content for
      // missing translations instead of throwing a MISSING_MESSAGE error.
      if (locale !== "en") {
        expect(title).not.toBe(EXPECTED_PRICING_TITLES["en"]);
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
