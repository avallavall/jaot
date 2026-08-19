import type { Metadata } from "next";
import type { ItemList, WithContext } from "schema-dts";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { BASE_URL } from "@/lib/seo/urls";
import { ssrJsonFetch } from "@/lib/seo/ssrFetch";
import { MarketplaceListingClient } from "@/components/marketplace/MarketplaceListingClient";

const apiUrl =
  process.env.API_PROXY_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return buildPageMetadata({ namespace: "metadata.marketplace", path: "/marketplace", locale });
}

/**
 * How many models the catalogue holds, for the structured data.
 *
 * The page rendered "All Models (107)" to a reader while the structured data
 * beside it published `numberOfItems: 0` — a module constant that could never
 * be anything else. Structured data is the one part of the page written for
 * machines, and it told them the marketplace was empty.
 *
 * One page of one item is enough: the answer carries the total. When the API
 * cannot be reached the count is left out rather than guessed, because an
 * absent number says "not stated" and a zero says "empty".
 */
async function catalogueSize(): Promise<number | null> {
  const result = await ssrJsonFetch<{ total?: number }>(
    `${apiUrl}/api/v2/models/catalog?page=1&page_size=1`,
    { label: "marketplace/itemList" },
  );
  if (result.status !== "ok" || typeof result.data.total !== "number") return null;
  return result.data.total;
}

export default async function MarketplacePage() {
  const total = await catalogueSize();
  const jsonLd: WithContext<ItemList> = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "JAOT Optimization Model Marketplace",
    description: "Browse ready-made optimization models",
    url: `${BASE_URL}/marketplace`,
    ...(total === null ? {} : { numberOfItems: total }),
    itemListOrder: "https://schema.org/ItemListUnordered",
  };

  return (
    <>
      <JsonLd data={jsonLd} />
      <MarketplaceListingClient />
    </>
  );
}
