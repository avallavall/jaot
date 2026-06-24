import type { Product, WithContext } from "schema-dts";

interface ProductInput {
  name: string;
  description: string;
  url: string;
  /** Optional: only include if category is visibly rendered in the DOM (D-03). */
  category?: string;
  priceEur: number;
  authorName?: string;
}

/** Returns a typed Product schema object for a marketplace model. */
export function buildProductSchema(input: ProductInput): WithContext<Product> {
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: input.name,
    description: input.description,
    url: input.url,
    ...(input.category !== undefined ? { category: input.category } : {}),
    brand: {
      "@type": "Organization",
      name: input.authorName?.trim() || "JAOT",
    } as WithContext<Product>["brand"],
    offers: {
      "@type": "Offer",
      price: input.priceEur.toString(),
      priceCurrency: "EUR",
      availability: "https://schema.org/InStock",
    } as WithContext<Product>["offers"],
  };
}
