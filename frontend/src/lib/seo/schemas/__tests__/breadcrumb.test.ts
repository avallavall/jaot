import { describe, it, expect } from "vitest";
import { buildBreadcrumbSchema } from "../breadcrumb";

describe("buildBreadcrumbSchema", () => {
  it("returns @context https://schema.org", () => {
    const result = buildBreadcrumbSchema([
      { name: "Home", url: "https://jaot.io" },
    ]) as unknown as Record<string, unknown>;
    expect(result["@context"]).toBe("https://schema.org");
  });

  it("returns @type BreadcrumbList", () => {
    const result = buildBreadcrumbSchema([
      { name: "Home", url: "https://jaot.io" },
    ]) as unknown as Record<string, unknown>;
    expect(result["@type"]).toBe("BreadcrumbList");
  });

  it("single item produces one ListItem with position 1", () => {
    const result = buildBreadcrumbSchema([
      { name: "Home", url: "https://jaot.io" },
    ]) as unknown as Record<string, unknown>;
    const items = result.itemListElement as Array<Record<string, unknown>>;
    expect(items).toHaveLength(1);
    expect(items[0]["@type"]).toBe("ListItem");
    expect(items[0].position).toBe(1);
  });

  it("two items produce correct positions 1 and 2", () => {
    const result = buildBreadcrumbSchema([
      { name: "Home", url: "https://jaot.io" },
      { name: "Pricing", url: "https://jaot.io/pricing" },
    ]) as unknown as Record<string, unknown>;
    const items = result.itemListElement as Array<Record<string, unknown>>;
    expect(items).toHaveLength(2);
    expect(items[0].position).toBe(1);
    expect(items[1].position).toBe(2);
  });

  it("items carry correct name and item (url)", () => {
    const result = buildBreadcrumbSchema([
      { name: "Home", url: "https://jaot.io" },
      { name: "Pricing", url: "https://jaot.io/pricing" },
    ]) as unknown as Record<string, unknown>;
    const items = result.itemListElement as Array<Record<string, unknown>>;
    expect(items[0].name).toBe("Home");
    expect(items[0].item).toBe("https://jaot.io");
    expect(items[1].name).toBe("Pricing");
    expect(items[1].item).toBe("https://jaot.io/pricing");
  });

  it("positions are 1-based (first is 1, not 0)", () => {
    const result = buildBreadcrumbSchema([
      { name: "Home", url: "https://jaot.io" },
      { name: "Marketplace", url: "https://jaot.io/marketplace" },
      { name: "Model", url: "https://jaot.io/marketplace/mdl_123" },
    ]) as unknown as Record<string, unknown>;
    const items = result.itemListElement as Array<Record<string, unknown>>;
    expect(items[0].position).toBe(1);
    expect(items[2].position).toBe(3);
  });
});
