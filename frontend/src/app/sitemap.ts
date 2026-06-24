import type { MetadataRoute } from "next";
import { buildAlternates, BASE_URL } from "@/lib/seo/urls";
import { getDocsPages } from "@/lib/docs/navigation";
import path from "path";
import fs from "fs";

// WR-03: project-launch sentinel — the single source of truth for every "no honest
// mtime available yet" fallback in this file (missing-MDX docs, sellers without an
// exposed author_created_at, and any static path that somehow lacks a lastMod).
// Update yearly until the backend exposes real mtimes for orgs and missing-MDX paths.
const FALLBACK_LAST_MODIFIED = new Date("2026-01-01");

// Guard against API drift: an unexpected null/undefined/non-ISO string produces
// an Invalid Date, which corrupts <lastmod> in the emitted XML.
function safeDate(value: string | null | undefined, fallback: Date): Date {
  if (!value) return fallback;
  const d = new Date(value);
  return isNaN(d.getTime()) ? fallback : d;
}

// WR-03: staticPages and STATIC_LAST_MODIFIED were previously two parallel const blocks
// (plus a third copy in sitemap.test.ts) that had to be kept in sync by hand — adding a
// page to one without the others silently fell back to the launch sentinel. Collapsed
// into ONE structure so path, changeFreq, priority and lastMod live together.
// Honest per-page approximation (D-06) — NOT new Date(), which Google de-values as an
// always-fresh signal (RESEARCH § Pitfall 7). Marketing pages last substantially changed
// 2026-05; legal pages rarely change. The single hardcoded
// /docs/getting-started/introduction entry is intentionally absent — it is now covered
// by the getDocsPages() loop (D-05).
const STATIC_PAGES = [
  { path: "", changeFrequency: "weekly" as const, priority: 1.0, lastMod: new Date("2026-05-01") }, // home — marketing
  { path: "/for-sellers", changeFrequency: "monthly" as const, priority: 0.8, lastMod: new Date("2026-05-01") }, // marketing
  { path: "/marketplace", changeFrequency: "daily" as const, priority: 0.9, lastMod: new Date("2026-05-01") }, // landing
  { path: "/terms", changeFrequency: "yearly" as const, priority: 0.3, lastMod: new Date("2026-01-01") }, // legal — rarely changes
  { path: "/privacy", changeFrequency: "yearly" as const, priority: 0.3, lastMod: new Date("2026-01-01") },
  { path: "/licenses", changeFrequency: "yearly" as const, priority: 0.3, lastMod: new Date("2026-01-01") },
] as const;

interface CatalogModel {
  id: string;
  created_at: string;
  updated_at: string; // D-06: exposed by Plan 01 Pydantic addition
  author_organization_id?: string | null;
  // v2.4 TODO: expose OrganizationPublicProfile.created_at through the catalog response.
  // Organization ORM has no updated_at column. Option A (RESEARCH § Critical Backend Gap):
  // use org.created_at as lastModified for seller entries. Currently NOT in the API response
  // (Plan 01 only added updated_at; author_created_at is a separate additive field).
  // Until exposed, seller entries fall back to new Date("2026-01-01").
  author_created_at?: string | null;
}

interface CatalogResponse {
  items: CatalogModel[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number; // D-04: pagination cursor
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Static page entries with locale alternates — WR-03: lastMod now lives on the same
  // record as the path, so there is no separate lookup that can silently miss.
  const staticEntries: MetadataRoute.Sitemap = STATIC_PAGES.map((page) => ({
    url: `${BASE_URL}${page.path}`,
    lastModified: page.lastMod,
    changeFrequency: page.changeFrequency,
    priority: page.priority,
    alternates: { languages: buildAlternates(page.path) },
  }));

  // D-05: docs entries via getDocsPages() from the static docsNavigation tree.
  // REQ-DRIFT: D-05 in CONTEXT.md described "auto-discovered from the filesystem" via
  // a recursive fs walk. RESEARCH.md corrects this — getDocsPages() over the static
  // docsNavigation constant is the project's canonical abstraction (dynamicParams = false
  // in docs/[...slug]/page.tsx means only these slugs are valid routes; an fs walk
  // would discover draft/orphan files and generate broken URLs).
  // fs.statSync is still used for per-entry mtime (D-06), not as a discovery mechanism.
  const docPages = getDocsPages(); // { title: string; slug: string }[]
  const docEntries: MetadataRoute.Sitemap = docPages.map((doc) => {
    let lastModified: Date = FALLBACK_LAST_MODIFIED; // WR-03: shared launch sentinel
    try {
      // process.cwd() resolves to frontend/ at Next.js build/ISR time (RESEARCH § Pattern 3)
      const mdxPath = path.join(process.cwd(), "content", "docs", `${doc.slug}.mdx`);
      lastModified = fs.statSync(mdxPath).mtime;
    } catch (err) {
      // File not found at expected path — use static fallback date (T-13.1-03e mitigation).
      // WR-04: log so on-disk MDX drift from docsNavigation is observable in SSR/build logs
      // rather than silently degrading every doc entry to the launch sentinel.
      console.error("[sitemap] doc mtime statSync failed", {
        slug: doc.slug,
        error: err instanceof Error ? err.message : String(err),
      });
    }
    return {
      url: `${BASE_URL}/docs/${doc.slug}`,
      lastModified,
      changeFrequency: "monthly" as const,
      priority: 0.7,
      alternates: { languages: buildAlternates(`/docs/${doc.slug}`) },
    };
  });

  // Dynamic entries from catalog API
  let modelEntries: MetadataRoute.Sitemap = [];
  let sellerEntries: MetadataRoute.Sitemap = [];

  try {
    const apiUrl =
      process.env.API_PROXY_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      "http://localhost:8001";

    // D-04: paginated catalog fetch — do/while loop over page=1..total_pages.
    // The catalog endpoint hard-caps page_size at 100 (FastAPI le=100 constraint).
    // No ?all=true parameter exists. Each page cached for 1h (T-13.1-03c mitigation).
    const models: CatalogModel[] = [];
    let page = 1;
    let totalPages = 1;
    do {
      const res = await fetch(
        `${apiUrl}/api/v2/models/catalog?page_size=100&page=${page}`,
        { next: { revalidate: 3600 } }
      );
      if (!res.ok) {
        // CR-02: Mid-walk failure — abort the entire catalog block into the outer
        // catch. A silent break would emit a truncated sitemap (only pages walked so
        // far); Google sees the URL count flap between ISR refreshes and de-trusts the
        // source. A clean degraded sitemap (static + docs only) is strictly better.
        throw new Error(`catalog page ${page} returned ${res.status}`);
      }
      const data: CatalogResponse = await res.json();
      models.push(...data.items);
      totalPages = data.total_pages;
      page++;
    } while (page <= totalPages);

    // Model detail page entries — D-06: use updated_at (Plan 01 added this field)
    // WR-01: guard against empty / special-char ids. A model id of "" would emit a
    // duplicate `/marketplace` URL (colliding with the static landing entry), and ids
    // containing / ? # or whitespace would produce malformed, unencoded sitemap URLs.
    // Prefixed IDs (generate_id) are [A-Za-z0-9_-] by contract; reject anything else.
    modelEntries = models
      .filter((model) => model.id && /^[A-Za-z0-9_-]+$/.test(model.id))
      .map((model) => ({
        url: `${BASE_URL}/marketplace/${model.id}`,
        lastModified: safeDate(model.updated_at, FALLBACK_LAST_MODIFIED), // NOT created_at (D-06)
        changeFrequency: "weekly" as const,
        priority: 0.7,
        alternates: { languages: buildAlternates(`/marketplace/${model.id}`) },
      }));

    // Seller profile entries from unique org IDs
    // D-06 Option A: use author_created_at (org.created_at) when available.
    // FALLBACK: new Date("2026-01-01") when author_created_at is not in the response.
    // author_created_at is NOT currently returned by the catalog endpoint (Plan 01
    // added only updated_at; Organization ORM has no updated_at column).
    // v2.4 TODO: expose OrganizationPublicProfile.created_at through the catalog response
    // so seller entries get honest lastModified values (tracked in CatalogModel interface above).
    // WR-01: same id-sanitization guard for seller orgIds — a malformed
    // author_organization_id would emit an unencoded /marketplace/sellers/<bad> URL.
    // Capture the first model per org in the SAME pass that dedupes org IDs — the
    // representative model supplies the seller's lastModified. Avoids a second
    // O(orgs × models) scan (a models.find per unique org) to recover data this loop
    // already walks past. Map preserves first-insertion order, matching the previous
    // Set-then-find ordering exactly.
    const orgFirstModel = new Map<string, CatalogModel>();
    for (const model of models) {
      const orgId = model.author_organization_id;
      if (orgId && /^[A-Za-z0-9_-]+$/.test(orgId) && !orgFirstModel.has(orgId)) {
        orgFirstModel.set(orgId, model);
      }
    }

    sellerEntries = Array.from(orgFirstModel, ([orgId, orgModel]) => {
      const sellerDate = safeDate(
        orgModel.author_created_at,
        FALLBACK_LAST_MODIFIED, // WR-03: shared launch sentinel
      );
      return {
        url: `${BASE_URL}/marketplace/sellers/${orgId}`,
        lastModified: sellerDate,
        changeFrequency: "weekly" as const,
        priority: 0.6,
        alternates: { languages: buildAlternates(`/marketplace/sellers/${orgId}`) },
      };
    });
  } catch (err) {
    // Graceful degradation: return static + doc entries if backend is unreachable.
    // WR-04: log so a silently-empty catalog block (typo'd proxy URL, backend down,
    // mid-walk failure per CR-02) surfaces in SSR logs instead of only via a Google
    // Search Console alert days later.
    console.error("[sitemap] catalog/seller block failed — emitting static + docs only", {
      error: err instanceof Error ? err.message : String(err),
    });
  }

  return [...staticEntries, ...docEntries, ...modelEntries, ...sellerEntries];
}
