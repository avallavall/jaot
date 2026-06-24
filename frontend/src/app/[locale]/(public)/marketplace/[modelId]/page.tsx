import type { Metadata } from "next";
import { cache } from "react";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { ModelDetailClient } from "@/components/marketplace/ModelDetailClient";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildProductSchema } from "@/lib/seo/schemas";
import { BASE_URL } from "@/lib/seo/urls";
import { ssrJsonFetch, type SsrFetchResult } from "@/lib/seo/ssrFetch";

const apiUrl =
  process.env.API_PROXY_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8001";

interface ModelData {
  id: string;
  display_name: string;
  description?: string;
  category: string;
  tags?: string[];
  price_eur: number;
  author_name?: string;
  avg_rating?: number;
  total_activations: number;
}

// cache(): dedupe the fetch + JSON parse across generateMetadata and the page body
// (both call fetchModel per request). React de-dupes by args for the render pass.
//
// Outcomes (see ssrJsonFetch): `notFound` → real HTTP 404 (audit F-04, the URL
// gets de-indexed). `unavailable` (rate-limit 429 / 5xx / network) → the page
// still renders a 200 with the client component loading the data and generic
// SEO, instead of a hard 500. The SSR fetch here only feeds metadata + JSON-LD;
// the visible content is rendered client-side by <ModelDetailClient>.
const fetchModel = cache((modelId: string): Promise<SsrFetchResult<ModelData>> => {
  return ssrJsonFetch<ModelData>(`${apiUrl}/api/v2/models/catalog/${modelId}`, {
    label: "marketplace/[modelId]",
  });
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; modelId: string }>;
}): Promise<Metadata> {
  const { locale, modelId } = await params;
  const result = await fetchModel(modelId);

  if (result.status === "notFound") {
    // Renders the branded [locale]/not-found.tsx with a real HTTP 404 (F-04)
    notFound();
  }

  const t = await getTranslations({ locale, namespace: "metadata" });

  if (result.status === "unavailable") {
    // Backend transiently unreachable (rate-limit/5xx). Don't 404 or throw —
    // ship generic-but-canonical marketplace metadata so the page still serves
    // a 200 and the client component loads the real data.
    return buildPageMetadata({
      path: `/marketplace/${modelId}`,
      locale,
      title: t("marketplace.title"),
      description: t("marketplace.description"),
    });
  }

  const model = result.data;
  // D-05: localized title chrome; {name} stays English per D-09 (catalog is not i18n'd)
  const title = t("dynamic.titleTemplate", { name: model.display_name });
  const description = (model.description ?? model.display_name).slice(0, 155);

  return buildPageMetadata({
    path: `/marketplace/${modelId}`,
    locale,
    title,
    description,
  });
  // canonical, alternates, og:image, og:siteName, og:locale all come from helper
}

export default async function ModelDetailPage({
  params,
}: {
  params: Promise<{ locale: string; modelId: string }>;
}) {
  const { modelId } = await params;
  const result = await fetchModel(modelId);

  if (result.status === "notFound") {
    // Real HTTP 404 + branded not-found page instead of a 200 soft-404 (F-04)
    notFound();
  }

  return (
    <>
      {result.status === "ok" && (
        // JSON-LD only when we have real data. On `unavailable` we still serve
        // the page (200) and let the client component load the model — better
        // than a 500 (model page) or a spurious 404 (audit F-04) on a transient
        // backend hiccup.
        <JsonLd
          data={buildProductSchema({
            name: result.data.display_name,
            description: result.data.description ?? result.data.display_name,
            url: `${BASE_URL}/marketplace/${modelId}`,
            priceEur: result.data.price_eur,
            authorName: result.data.author_name,
          })}
        />
      )}
      <ModelDetailClient modelId={modelId} />
    </>
  );
}
