import type { BreadcrumbList, ListItem, WithContext } from "schema-dts";

interface BreadcrumbItem {
  name: string;
  url: string;
}

/** Returns a typed BreadcrumbList schema object from an ordered list of items. */
export function buildBreadcrumbSchema(items: BreadcrumbItem[]): WithContext<BreadcrumbList> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map(
      (item, index): WithContext<ListItem> => ({
        "@context": "https://schema.org",
        "@type": "ListItem",
        position: index + 1,
        name: item.name,
        item: item.url,
      })
    ),
  };
}
