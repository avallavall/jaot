import { getRequestConfig } from "next-intl/server";
import { hasLocale, IntlErrorCode } from "next-intl";
import { routing } from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;

  // Always load English as the baseline for fallback
  const enMessages = (await import("../../messages/en.json")).default;

  let messages: Record<string, unknown>;

  if (locale === "en") {
    messages = enMessages;
  } else {
    // Load locale-specific messages; file may not exist yet (created incrementally)
    try {
      messages = (await import(`../../messages/${locale}.json`)).default;
    } catch {
      messages = {};
    }
  }

  return {
    locale,
    messages,
    onError(error) {
      if (error.code === IntlErrorCode.MISSING_MESSAGE) {
        // Only warn in development to avoid noise in production
        if (process.env.NODE_ENV === "development") {
          console.warn(`[i18n] Missing translation: ${error.message}`);
        }
      } else {
        // Re-report non-missing-message errors normally
        console.error(error);
      }
    },
    getMessageFallback({ namespace, key, error }) {
      if (error.code === IntlErrorCode.MISSING_MESSAGE) {
        // Walk the English messages to find the fallback string
        const path = namespace ? `${namespace}.${key}` : key;
        const parts = path.split(".");
        let current: unknown = enMessages;
        for (const part of parts) {
          if (current && typeof current === "object" && part in current) {
            current = (current as Record<string, unknown>)[part];
          } else {
            return `${namespace}.${key}`;
          }
        }
        if (typeof current === "string") {
          // Wrap with zero-width space markers for FallbackText detection
          return `\u200B${current}\u200B`;
        }
        return `${namespace}.${key}`;
      }
      return `${namespace}.${key}`;
    },
  };
});
