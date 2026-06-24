import { describe, it, expect } from "vitest";
import { routing } from "../routing";

describe("i18n routing configuration", () => {
  it("defines exactly 5 supported locales", () => {
    expect(routing.locales).toHaveLength(5);
  });

  it("includes all expected locale codes", () => {
    const expected = ["en", "es", "ca", "fr", "de"];
    for (const locale of expected) {
      expect(routing.locales).toContain(locale);
    }
  });

  it("sets English as the default locale", () => {
    expect(routing.defaultLocale).toBe("en");
  });

  it("uses as-needed locale prefix so English has no URL prefix", () => {
    expect(routing.localePrefix).toBe("as-needed");
  });

  it("configures NEXT_LOCALE cookie with one-year TTL", () => {
    expect(routing.localeCookie).toBeDefined();
    const cookie = routing.localeCookie as { name: string; maxAge: number };
    expect(cookie.name).toBe("NEXT_LOCALE");
    // 1 year in seconds = 60 * 60 * 24 * 365 = 31536000
    expect(cookie.maxAge).toBe(31536000);
  });
});
