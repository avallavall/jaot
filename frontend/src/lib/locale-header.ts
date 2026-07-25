import { routing } from "@/i18n/routing";

/**
 * The locale the user is reading the app in, taken from the URL prefix that
 * next-intl routes on.
 *
 * Sent with every request that can make the backend GENERATE text (assistant
 * replies, explanations) so the answer comes back in the language the user is
 * actually reading, not always in English. Returns nothing outside the browser
 * or on an unprefixed path; the backend then falls back to its default.
 */
export function localeHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const segment = window.location.pathname.split("/")[1];
  return routing.locales.includes(segment as (typeof routing.locales)[number])
    ? { "X-JAOT-Locale": segment }
    : {};
}
