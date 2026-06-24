import { describe, it, expect } from "vitest";
import { buildProductSchema } from "../product";

const baseInput = {
  name: "X",
  description: "Y",
  url: "https://jaot.io/marketplace/abc",
  category: "linear",
  priceEur: 9.99,
};

describe("buildProductSchema", () => {
  it("returns @type Product", () => {
    const result = buildProductSchema(baseInput) as unknown as Record<string, unknown>;
    expect(result["@type"]).toBe("Product");
  });

  it("returns @context https://schema.org", () => {
    const result = buildProductSchema(baseInput) as unknown as Record<string, unknown>;
    expect(result["@context"]).toBe("https://schema.org");
  });

  it("returns name from input", () => {
    const result = buildProductSchema({
      ...baseInput,
      name: "My Model",
    }) as unknown as Record<string, unknown>;
    expect(result.name).toBe("My Model");
  });

  it("returns description from input", () => {
    const result = buildProductSchema({
      ...baseInput,
      description: "A description",
    }) as unknown as Record<string, unknown>;
    expect(result.description).toBe("A description");
  });

  it("returns url from input", () => {
    const result = buildProductSchema({
      ...baseInput,
      url: "https://jaot.io/marketplace/mdl_xyz",
    }) as unknown as Record<string, unknown>;
    expect(result.url).toBe("https://jaot.io/marketplace/mdl_xyz");
  });

  it("category is set from input", () => {
    const result = buildProductSchema({
      ...baseInput,
      category: "linear",
    }) as unknown as Record<string, unknown>;
    expect(result.category).toBe("linear");
  });

  it("offers has @type Offer with price string, priceCurrency and availability", () => {
    const result = buildProductSchema({
      ...baseInput,
      priceEur: 9.99,
    }) as unknown as Record<string, unknown>;
    const offers = result.offers as Record<string, unknown>;
    expect(offers["@type"]).toBe("Offer");
    expect(offers.price).toBe("9.99");
    expect(offers.priceCurrency).toBe("EUR");
    expect(offers.availability).toBe("https://schema.org/InStock");
  });

  it("brand.name uses authorName when provided", () => {
    const result = buildProductSchema({
      ...baseInput,
      authorName: "Alice",
    }) as unknown as Record<string, unknown>;
    const brand = result.brand as Record<string, unknown>;
    expect(brand.name).toBe("Alice");
  });

  it("brand.name falls back to JAOT when authorName is undefined", () => {
    const result = buildProductSchema({
      ...baseInput,
      authorName: undefined,
    }) as unknown as Record<string, unknown>;
    const brand = result.brand as Record<string, unknown>;
    expect(brand.name).toBe("JAOT");
  });

  it("brand.name falls back to JAOT when authorName is empty string", () => {
    const result = buildProductSchema({
      ...baseInput,
      authorName: "",
    }) as unknown as Record<string, unknown>;
    const brand = result.brand as Record<string, unknown>;
    expect(brand.name).toBe("JAOT");
  });
});
