/**
 * Locale helpers for E2E tests.
 *
 * next-intl uses `localePrefix: "as-needed"` so English (default) has no
 * prefix while every other locale gets `/{locale}` prepended.
 */

export const DEFAULT_LOCALE = "en";

/**
 * Return the locale-prefixed path.
 *
 * - English / undefined locale: returns path unchanged.
 * - Other locales: prepends `/{locale}`.
 * - Edge cases: root `/` or empty string with a non-default locale returns `/{locale}`.
 */
export function localePath(path: string, locale?: string): string {
  if (!locale || locale === DEFAULT_LOCALE) {
    return path;
  }
  const normalized = path === "/" || path === "" ? "" : path;
  return `/${locale}${normalized}`;
}

/**
 * Return an unanchored RegExp matching the (optionally locale-prefixed) path.
 *
 * Useful for `expect(page).toHaveURL(localeURL("/login", "es"))`.
 */
export function localeURL(path: string, locale?: string): RegExp {
  const target = localePath(path, locale);
  const escaped = target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(escaped);
}
