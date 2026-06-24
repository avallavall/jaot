import type { Organization, WebSite, WithContext } from "schema-dts";

/** Returns a typed Organization schema object for JAOT. */
export function buildOrganizationSchema(baseUrl: string): WithContext<Organization> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "JAOT",
    url: baseUrl,
    logo: `${baseUrl}/jaot-logo.png`,
  };
}

/** Returns a typed WebSite schema object with a SearchAction potentialAction. */
export function buildWebSiteSchema(baseUrl: string): WithContext<WebSite> {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "JAOT",
    url: baseUrl,
    potentialAction: {
      "@type": "SearchAction",
      target: `${baseUrl}/marketplace?search={search_term_string}`,
      "query-input": "required name=search_term_string",
    } as WithContext<WebSite>["potentialAction"],
  };
}
