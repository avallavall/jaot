import { test, expect } from "@playwright/test";

// D-10: 4 pages × 5 locales = 20 scenarios
// Pages cover one representative per page TYPE: home (root), static (pricing),
// dynamic listing (marketplace), dynamic detail/content (docs intro).
const LOCALES = ["en", "es", "ca", "fr", "de"] as const;

// BASE_URL must match the site URL used at build time (NEXT_PUBLIC_SITE_URL).
// Playwright's baseURL is for page.goto() only; canonical assertions use absolute URLs.
const BASE_URL = process.env.BASE_URL || "https://jaot.io";

const PAGES = [
  "/",
  "/pricing",
  "/marketplace",
  "/docs/getting-started/introduction",
];

// Inline helpers — test-local copies, not imported from app code (keeps the spec self-contained).
// Contract: localePrefix "as-needed" means "en" gets no prefix; all others get /{locale}.
// Root path ("/") is a special case: Next.js layout.tsx emits the bare BASE_URL (no trailing slash)
// for the English home, and BASE_URL/{locale} (no trailing slash) for locale homes.
function localizedPath(pagePath: string, locale: string): string {
  if (locale === "en") return pagePath;
  // Strip trailing slash from the root path to match Next.js canonical output.
  return `/${locale}${pagePath === "/" ? "" : pagePath}`;
}

function localizedUrl(pagePath: string, locale: string): string {
  if (locale === "en" && pagePath === "/") return BASE_URL;
  return `${BASE_URL}${localizedPath(pagePath, locale)}`;
}

// D-12: CI build only — runs against prod Docker build (target: runner), NOT npm run dev.
// No auth setup, no mocking — hits real SSR'd HTML (per integration_proof.md Phase 11 policy).
test.describe("SEO canonical + hreflang per locale", () => {
  for (const pagePath of PAGES) {
    for (const locale of LOCALES) {
      test(
        `canonical + hreflang: ${locale} ${pagePath}`,
        async ({ page }) => {
          // Navigate using the localized path (avoids /en → / redirect in next-intl as-needed).
          const navPath = localizedPath(pagePath, locale);
          await page.goto(navPath);

          // D-11 assertion 1: canonical href must equal the navigated URL (D-07).
          // EN: https://jaot.io/pricing — ES: https://jaot.io/es/pricing (NOT https://jaot.io/pricing).
          const canonical = await page
            .locator('link[rel="canonical"]')
            .getAttribute("href");
          expect(canonical).toBe(localizedUrl(pagePath, locale));

          // D-11 assertion 2: exactly 6 alternate entries (en, es, ca, fr, de, x-default).
          // Strict equality — NOT ">= 5" (that masks duplicate or missing entries).
          const alternates = await page
            .locator('link[rel="alternate"][hreflang]')
            .all();
          expect(alternates).toHaveLength(6);

          // D-11 assertion 3: each hreflang href must point to the correct locale URL.
          // e.g., on /es/pricing the hreflang="ca" MUST be https://jaot.io/ca/pricing.
          for (const loc of LOCALES) {
            const href = await page
              .locator(`link[rel="alternate"][hreflang="${loc}"]`)
              .getAttribute("href");
            expect(href).toBe(localizedUrl(pagePath, loc));
          }

          // D-11 assertion 4: x-default points to the English URL (no /en prefix per as-needed).
          const xDefaultHref = await page
            .locator('link[rel="alternate"][hreflang="x-default"]')
            .getAttribute("href");
          expect(xDefaultHref).toBe(localizedUrl(pagePath, "en"));
        },
      );
    }
  }
});
