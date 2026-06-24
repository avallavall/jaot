import { describe, it, expect } from "vitest";
import { localizedUrl, buildAlternates } from "../urls";

describe("localizedUrl", () => {
  it("en root → base URL with no trailing slash", () => {
    expect(localizedUrl("", "en")).toBe("https://jaot.io");
  });

  it("es root → base URL + /es (no trailing slash)", () => {
    expect(localizedUrl("", "es")).toBe("https://jaot.io/es");
  });

  it("en non-root → base URL + path (no /en prefix)", () => {
    expect(localizedUrl("/pricing", "en")).toBe("https://jaot.io/pricing");
  });

  it("fr non-root → base URL + /fr + path", () => {
    expect(localizedUrl("/pricing", "fr")).toBe("https://jaot.io/fr/pricing");
  });

  it("ca non-root → base URL + /ca + path", () => {
    expect(localizedUrl("/marketplace", "ca")).toBe("https://jaot.io/ca/marketplace");
  });

  it("de non-root → base URL + /de + path", () => {
    expect(localizedUrl("/contact", "de")).toBe("https://jaot.io/de/contact");
  });
});

describe("buildAlternates", () => {
  it("non-root: x-default is the en URL (no /en prefix)", () => {
    const result = buildAlternates("/pricing");
    expect(result["x-default"]).toBe("https://jaot.io/pricing");
  });

  it("non-root: contains all 5 locale keys", () => {
    const result = buildAlternates("/pricing");
    expect(result).toHaveProperty("en");
    expect(result).toHaveProperty("es");
    expect(result).toHaveProperty("ca");
    expect(result).toHaveProperty("fr");
    expect(result).toHaveProperty("de");
  });

  it("non-root: en URL has no locale prefix", () => {
    const result = buildAlternates("/pricing");
    expect(result["en"]).toBe("https://jaot.io/pricing");
  });

  it("non-root: es URL has /es prefix", () => {
    const result = buildAlternates("/pricing");
    expect(result["es"]).toBe("https://jaot.io/es/pricing");
  });

  it("non-root: fr URL has /fr prefix", () => {
    const result = buildAlternates("/pricing");
    expect(result["fr"]).toBe("https://jaot.io/fr/pricing");
  });

  it("root path: x-default is base URL (no trailing slash)", () => {
    const result = buildAlternates("");
    expect(result["x-default"]).toBe("https://jaot.io");
  });

  it("root path: en URL is base URL (no trailing slash)", () => {
    const result = buildAlternates("");
    expect(result["en"]).toBe("https://jaot.io");
  });

  it("root path: es URL is base URL + /es (no trailing slash)", () => {
    const result = buildAlternates("");
    expect(result["es"]).toBe("https://jaot.io/es");
  });

  it("root path: contains all 5 locale keys", () => {
    const result = buildAlternates("");
    expect(result).toHaveProperty("en");
    expect(result).toHaveProperty("es");
    expect(result).toHaveProperty("ca");
    expect(result).toHaveProperty("fr");
    expect(result).toHaveProperty("de");
  });

  it("x-default is NOT a /en/ prefixed URL", () => {
    const result = buildAlternates("/pricing");
    expect(result["x-default"]).not.toContain("/en/");
  });
});
