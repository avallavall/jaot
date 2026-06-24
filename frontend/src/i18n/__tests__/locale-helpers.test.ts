/**
 * Unit tests for E2E locale helpers (Phase 53).
 * These are pure functions so we test them in vitest rather than Playwright.
 */
import { describe, it, expect } from "vitest";
import { localePath, localeURL, DEFAULT_LOCALE } from "../../../e2e/helpers/locale";

describe("localePath", () => {
  it("returns path unchanged for English (default locale)", () => {
    expect(localePath("/login", "en")).toBe("/login");
    expect(localePath("/marketplace", "en")).toBe("/marketplace");
  });

  it("returns path unchanged when no locale is provided", () => {
    expect(localePath("/login")).toBe("/login");
    expect(localePath("/marketplace")).toBe("/marketplace");
  });

  it("prepends locale prefix for non-English locales", () => {
    expect(localePath("/login", "es")).toBe("/es/login");
    expect(localePath("/marketplace", "fr")).toBe("/fr/marketplace");
  });

  it("handles root path for non-default locale", () => {
    expect(localePath("/", "es")).toBe("/es");
  });

  it("handles empty string path for non-default locale", () => {
    expect(localePath("", "es")).toBe("/es");
  });

  it("returns root path unchanged for English", () => {
    expect(localePath("/", "en")).toBe("/");
    expect(localePath("/")).toBe("/");
  });
});

describe("localeURL", () => {
  it("returns a RegExp for path assertions", () => {
    const result = localeURL("/login", "es");
    expect(result).toBeInstanceOf(RegExp);
  });

  it("matches locale-prefixed URL for non-English locale", () => {
    const pattern = localeURL("/login", "es");
    expect(pattern.test("/es/login")).toBe(true);
  });

  it("matches unprefixed URL for English locale", () => {
    const pattern = localeURL("/login", "en");
    expect(pattern.test("/login")).toBe(true);
  });

  it("escapes special regex characters in path", () => {
    // Paths with dots or other special chars should not break regex
    const pattern = localeURL("/api/v2.1/docs", "es");
    expect(pattern.test("/es/api/v2.1/docs")).toBe(true);
    // Should NOT match a different character in place of dot
    expect(pattern.test("/es/api/v2X1/docs")).toBe(false);
  });
});

describe("DEFAULT_LOCALE", () => {
  it("is English", () => {
    expect(DEFAULT_LOCALE).toBe("en");
  });
});
