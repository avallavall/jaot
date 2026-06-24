import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getDocsPages } from "@/lib/docs/navigation";
import { capitalizeSegment } from "@/lib/docs/breadcrumb-label";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildBreadcrumbSchema } from "@/lib/seo/schemas";
import { BASE_URL } from "@/lib/seo/urls";

interface Props {
  params: Promise<{ slug: string[]; locale: string }>;
}

// Static content map -- webpack needs static analysis for MDX imports.
// Each MDX file must be explicitly imported for the @next/mdx loader to process it.
const contentMap: Record<string, () => Promise<{ default: React.ComponentType; frontmatter?: Record<string, string> }>> = {
  "getting-started/introduction": () => import("@content/docs/getting-started/introduction.mdx"),
  "getting-started/quick-start": () => import("@content/docs/getting-started/quick-start.mdx"),
  "getting-started/authentication": () => import("@content/docs/getting-started/authentication.mdx"),
  "ai-builder/building-with-ai": () => import("@content/docs/ai-builder/building-with-ai.mdx"),
  "ai-builder/templates-gallery": () => import("@content/docs/ai-builder/templates-gallery.mdx"),
  "marketplace/browsing-models": () => import("@content/docs/marketplace/browsing-models.mdx"),
  "marketplace/publishing-models": () => import("@content/docs/marketplace/publishing-models.mdx"),
  "mcp/overview": () => import("@content/docs/mcp/overview.mdx"),
  "api/solve": () => import("@content/docs/api/solve.mdx"),
  "api/models": () => import("@content/docs/api/models.mdx"),
  "api/executions": () => import("@content/docs/api/executions.mdx"),
  "api/credits-billing": () => import("@content/docs/api/credits-billing.mdx"),
  "api/api-keys": () => import("@content/docs/api/api-keys.mdx"),
  "api/notifications": () => import("@content/docs/api/notifications.mdx"),
  "api/triggers": () => import("@content/docs/api/triggers.mdx"),
  "api/versions": () => import("@content/docs/api/versions.mdx"),
  "api/webhooks": () => import("@content/docs/api/webhooks.mdx"),
  "api/health": () => import("@content/docs/api/health.mdx"),
  "api/admin": () => import("@content/docs/api/admin.mdx"),
  "api/websocket": () => import("@content/docs/api/websocket.mdx"),
  "reference/errors": () => import("@content/docs/reference/errors.mdx"),
  "reference/rate-limits-credits": () => import("@content/docs/reference/rate-limits-credits.mdx"),
  "guides/index": () => import("@content/docs/guides/index.mdx"),
  "guides/production-planning": () => import("@content/docs/guides/production-planning.mdx"),
  "guides/cutting-and-packing": () => import("@content/docs/guides/cutting-and-packing.mdx"),
  "guides/food-and-beverage": () => import("@content/docs/guides/food-and-beverage.mdx"),
  "guides/textile-manufacturing": () => import("@content/docs/guides/textile-manufacturing.mdx"),
  "guides/chemical-process": () => import("@content/docs/guides/chemical-process.mdx"),
  "guides/construction-planning": () => import("@content/docs/guides/construction-planning.mdx"),
  "guides/portfolio-optimization": () => import("@content/docs/guides/portfolio-optimization.mdx"),
  "guides/insurance-risk": () => import("@content/docs/guides/insurance-risk.mdx"),
  "guides/real-estate-investment": () => import("@content/docs/guides/real-estate-investment.mdx"),
  "guides/route-and-fleet": () => import("@content/docs/guides/route-and-fleet.mdx"),
  "guides/transportation-network": () => import("@content/docs/guides/transportation-network.mdx"),
  "guides/maritime-shipping": () => import("@content/docs/guides/maritime-shipping.mdx"),
  "guides/railway-operations": () => import("@content/docs/guides/railway-operations.mdx"),
  "guides/facility-location": () => import("@content/docs/guides/facility-location.mdx"),
  "guides/warehouse-operations": () => import("@content/docs/guides/warehouse-operations.mdx"),
  "guides/supply-chain-planning": () => import("@content/docs/guides/supply-chain-planning.mdx"),
  "guides/energy-grid": () => import("@content/docs/guides/energy-grid.mdx"),
  "guides/environmental-management": () => import("@content/docs/guides/environmental-management.mdx"),
  "guides/water-distribution": () => import("@content/docs/guides/water-distribution.mdx"),
  "guides/healthcare-resources": () => import("@content/docs/guides/healthcare-resources.mdx"),
  "guides/pharmaceutical-production": () => import("@content/docs/guides/pharmaceutical-production.mdx"),
  "guides/telecom-network": () => import("@content/docs/guides/telecom-network.mdx"),
  "guides/network-graph": () => import("@content/docs/guides/network-graph.mdx"),
  "guides/advertising-media": () => import("@content/docs/guides/advertising-media.mdx"),
  "guides/retail-assortment": () => import("@content/docs/guides/retail-assortment.mdx"),
  "guides/workforce-scheduling": () => import("@content/docs/guides/workforce-scheduling.mdx"),
  "guides/sports-scheduling": () => import("@content/docs/guides/sports-scheduling.mdx"),
  "guides/education-timetabling": () => import("@content/docs/guides/education-timetabling.mdx"),
  "guides/agricultural-planning": () => import("@content/docs/guides/agricultural-planning.mdx"),
  "guides/mining-operations": () => import("@content/docs/guides/mining-operations.mdx"),
  "guides/forestry-management": () => import("@content/docs/guides/forestry-management.mdx"),
  "guides/government-resources": () => import("@content/docs/guides/government-resources.mdx"),
  "guides/aerospace-mission": () => import("@content/docs/guides/aerospace-mission.mdx"),
  "guides/getting-started-optimization": () => import("@content/docs/guides/getting-started-optimization.mdx"),
};

export async function generateStaticParams() {
  const pages = getDocsPages();
  return pages.map((page) => ({ slug: page.slug.split("/") }));
}

export const dynamicParams = false;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, locale } = await params;
  const slugPath = slug.join("/");
  const loader = contentMap[slugPath];
  if (!loader) return {};
  try {
    const mod = await loader();
    const frontmatter = mod.frontmatter ?? {};
    // Raw frontmatter title passed as-is (RESEARCH Open Q1 — no "{title} — JAOT Docs" wrapper)
    return buildPageMetadata({
      path: `/docs/${slug.join("/")}`,
      locale,
      title: frontmatter.title,
      description: frontmatter.description,
    });
  } catch (err) {
    // WR-04: log so a frontmatter/loader failure (corrupt MDX, build drift) is observable
    // in SSR logs rather than silently emitting empty (untitled, un-canonicalized) metadata.
    console.error("[docs/[...slug]] generateMetadata loader failed", {
      slug: slugPath,
      error: err instanceof Error ? err.message : String(err),
    });
    return {};
  }
}

export default async function DocsPage({ params }: Props) {
  const { slug } = await params;
  const slugPath = slug.join("/");
  const loader = contentMap[slugPath];
  if (!loader) notFound();
  const { default: Content } = await loader().catch((err) => {
    // WR-04: log the real failure cause before falling through to the 404 — otherwise a
    // broken content module is indistinguishable from a genuinely-missing slug in logs.
    console.error("[docs/[...slug]] content loader failed", {
      slug: slugPath,
      error: err instanceof Error ? err.message : String(err),
    });
    notFound();
  });

  // BreadcrumbList items derived server-side from params.slug. DocsBreadcrumbs is "use client"
  // (usePathname) so it can't supply the items here, but both call the shared capitalizeSegment
  // + BASE_URL, so the visible breadcrumb DOM and this JSON-LD never diverge (D-08 single source).
  const breadcrumbSegments = ["docs", ...slug];
  const breadcrumbItems = breadcrumbSegments.map((seg, i) => ({
    name: capitalizeSegment(seg),
    url: `${BASE_URL}/${breadcrumbSegments.slice(0, i + 1).join("/")}`,
  }));

  return (
    <>
      <JsonLd data={buildBreadcrumbSchema(breadcrumbItems)} />
      <Content />
    </>
  );
}
