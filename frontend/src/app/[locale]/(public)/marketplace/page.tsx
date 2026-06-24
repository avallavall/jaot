import type { Metadata } from "next";
import type { ItemList, WithContext } from "schema-dts";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { BASE_URL } from "@/lib/seo/urls";
import { MarketplaceListingClient } from "@/components/marketplace/MarketplaceListingClient";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return buildPageMetadata({ namespace: "metadata.marketplace", path: "/marketplace", locale });
}

const jsonLd: WithContext<ItemList> = {
  "@context": "https://schema.org",
  "@type": "ItemList",
  name: "JAOT Optimization Model Marketplace",
  description: "Browse ready-made optimization models",
  url: `${BASE_URL}/marketplace`,
  numberOfItems: 0,
  itemListOrder: "https://schema.org/ItemListUnordered",
};

export default function MarketplacePage() {
  return (
    <>
      <JsonLd data={jsonLd} />
      <MarketplaceListingClient />
    </>
  );
}
