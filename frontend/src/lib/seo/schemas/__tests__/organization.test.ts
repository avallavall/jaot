import { describe, it, expect } from "vitest";
import { buildOrganizationSchema, buildWebSiteSchema } from "../organization";

describe("buildOrganizationSchema", () => {
  it("returns @context https://schema.org", () => {
    const result = buildOrganizationSchema("https://jaot.io") as unknown as Record<
      string,
      unknown
    >;
    expect(result["@context"]).toBe("https://schema.org");
  });

  it("returns @type Organization", () => {
    const result = buildOrganizationSchema("https://jaot.io") as unknown as Record<
      string,
      unknown
    >;
    expect(result["@type"]).toBe("Organization");
  });

  it("returns name JAOT", () => {
    const result = buildOrganizationSchema("https://jaot.io") as unknown as Record<
      string,
      unknown
    >;
    expect(result.name).toBe("JAOT");
  });

  it("returns url equal to baseUrl", () => {
    const result = buildOrganizationSchema("https://jaot.io") as unknown as Record<
      string,
      unknown
    >;
    expect(result.url).toBe("https://jaot.io");
  });

  it("accepts a custom baseUrl", () => {
    const result = buildOrganizationSchema("https://example.com") as unknown as Record<
      string,
      unknown
    >;
    expect(result.url).toBe("https://example.com");
    expect(result["@context"]).toBe("https://schema.org");
    expect(result["@type"]).toBe("Organization");
  });
});

describe("buildWebSiteSchema", () => {
  it("returns @context https://schema.org", () => {
    const result = buildWebSiteSchema("https://jaot.io") as unknown as Record<string, unknown>;
    expect(result["@context"]).toBe("https://schema.org");
  });

  it("returns @type WebSite", () => {
    const result = buildWebSiteSchema("https://jaot.io") as unknown as Record<string, unknown>;
    expect(result["@type"]).toBe("WebSite");
  });

  it("returns potentialAction with @type SearchAction", () => {
    const result = buildWebSiteSchema("https://jaot.io") as unknown as Record<string, unknown>;
    expect(result.potentialAction).toBeDefined();
    const action = result.potentialAction as Record<string, unknown>;
    expect(action["@type"]).toBe("SearchAction");
  });

  it("potentialAction target contains {search_term_string}", () => {
    const result = buildWebSiteSchema("https://jaot.io") as unknown as Record<string, unknown>;
    const action = result.potentialAction as Record<string, unknown>;
    expect(String(action.target)).toContain("{search_term_string}");
  });

  it("potentialAction target contains baseUrl", () => {
    const result = buildWebSiteSchema("https://jaot.io") as unknown as Record<string, unknown>;
    const action = result.potentialAction as Record<string, unknown>;
    expect(String(action.target)).toContain("https://jaot.io");
  });

  it("potentialAction target uses ?search= param (not ?q=)", () => {
    const result = buildWebSiteSchema("https://jaot.io") as unknown as Record<string, unknown>;
    const action = result.potentialAction as Record<string, unknown>;
    expect(String(action.target)).toContain("?search=");
    expect(String(action.target)).not.toContain("?q=");
  });
});
