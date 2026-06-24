import type { Metadata } from "next";
import { cache } from "react";
import type { Organization, WithContext } from "schema-dts";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { BASE_URL } from "@/lib/seo/urls";
import { SellerProfileClient } from "@/components/marketplace/SellerProfileClient";
import { ssrJsonFetch, type SsrFetchResult } from "@/lib/seo/ssrFetch";

const apiUrl =
  process.env.API_PROXY_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8001";

interface OrgProfileData {
  id: string;
  name: string;
  bio?: string;
  logo_url?: string;
  website_url?: string;
}

// cache(): dedupe the fetch + JSON parse across generateMetadata and the page body
// (both call fetchOrgProfile per request). React de-dupes by args for the render pass.
//
// `notFound` → real 404 (unknown/deleted seller). `unavailable` (rate-limit
// 429 / 5xx / network) → still render a 200 with the client component loading
// the profile, rather than a spurious 404 that de-indexes a live seller on a
// transient backend hiccup. The SSR fetch only feeds SEO metadata + JSON-LD.
const fetchOrgProfile = cache((orgId: string): Promise<SsrFetchResult<OrgProfileData>> => {
  return ssrJsonFetch<OrgProfileData>(`${apiUrl}/api/v2/organizations/${orgId}/public`, {
    label: "marketplace/sellers/[orgId]",
  });
});

/** Return the URL only when it is a valid https:// URL. Guards seller-supplied
 *  website_url / logo_url from injecting arbitrary or non-https URIs into the
 *  Organization JSON-LD (SEO-injection hygiene). */
function safeHttpsUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;
  try {
    return new URL(url).protocol === "https:" ? url : undefined;
  } catch {
    return undefined;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; orgId: string }>;
}): Promise<Metadata> {
  const { locale, orgId } = await params;
  const result = await fetchOrgProfile(orgId);

  if (result.status === "notFound") {
    return { title: "Seller Profile | JAOT" };
  }

  const t = await getTranslations({ locale, namespace: "metadata" });

  if (result.status === "unavailable") {
    // Transient backend failure — generic-but-canonical metadata, page still 200s.
    return buildPageMetadata({
      path: `/marketplace/sellers/${orgId}`,
      locale,
      title: t("sellers.title"),
      description: t("sellers.description"),
    });
  }

  const profile = result.data;
  // D-05: localized title chrome; {name} stays English per D-09 (catalog is not i18n'd)
  const title = t("dynamic.titleTemplate", { name: profile.name });
  const description =
    profile.bio?.slice(0, 155) ||
    t("dynamic.sellerDescriptionFallback", { name: profile.name });

  return buildPageMetadata({
    path: `/marketplace/sellers/${orgId}`,
    locale,
    title,
    description,
  });
  // canonical, alternates, og:image, og:siteName, og:locale all come from helper
}

export default async function SellerProfilePage({
  params,
}: {
  params: Promise<{ locale: string; orgId: string }>;
}) {
  const { orgId } = await params;
  const result = await fetchOrgProfile(orgId);

  if (result.status === "notFound") {
    // Unknown / deleted seller — return a real 404 instead of an empty 200 page
    // that crawlers would index.
    notFound();
  }

  // JSON-LD only when we have real data. On `unavailable` the page still serves
  // a 200 and the client component loads the profile — better than a spurious
  // 404 on a transient backend hiccup.
  let jsonLd: WithContext<Organization> | null = null;
  if (result.status === "ok") {
    const profile = result.data;
    // Seller-supplied website_url/logo_url are validated to https before inclusion;
    // <JsonLd> escapes </script> + & so the schema is injection-safe.
    const logo = safeHttpsUrl(profile.logo_url);
    jsonLd = {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: profile.name,
      description: profile.bio || "",
      url: safeHttpsUrl(profile.website_url) ?? `${BASE_URL}/marketplace/sellers/${orgId}`,
      ...(logo ? { logo } : {}),
    };
  }

  return (
    <>
      {jsonLd && <JsonLd data={jsonLd} />}
      <SellerProfileClient orgId={orgId} />
    </>
  );
}
