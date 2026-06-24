export const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://jaot.io";
const LOCALES = ["en", "es", "ca", "fr", "de"] as const;
export type Locale = (typeof LOCALES)[number];

/** Returns the absolute URL for a path + locale, respecting the as-needed prefix rule.
 *  en → no /en prefix (e.g. https://jaot.io/pricing)
 *  other locales → /{locale} prefix (e.g. https://jaot.io/es/pricing)
 */
export function localizedUrl(path: string, locale: Locale): string {
  return locale === "en" ? `${BASE_URL}${path}` : `${BASE_URL}/${locale}${path}`;
}

/** Returns the hreflang alternates map including x-default, for Next.js Metadata.alternates.languages.
 *  x-default points to the English URL (as-needed: no /en prefix).
 *  Returns a FLAT Record<string, string> with keys: x-default, en, es, ca, fr, de.
 *  D-12: x-default is emitted on every call (unifies the three existing call sites toward the more correct shape).
 */
export function buildAlternates(path: string): Record<string, string> {
  const langs: Record<string, string> = {
    "x-default": localizedUrl(path, "en"),
  };
  for (const loc of LOCALES) {
    langs[loc] = localizedUrl(path, loc);
  }
  return langs;
}
