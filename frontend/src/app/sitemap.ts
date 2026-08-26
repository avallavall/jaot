import type { MetadataRoute } from "next";
import { buildAlternates, BASE_URL } from "@/lib/seo/urls";
import { getDocsPages } from "@/lib/docs/navigation";
import { SSR_REQUEST_HEADERS } from "@/lib/seo/ssrFetch";
import path from "path";
import fs from "fs";

// WR-03: project-launch sentinel — the single source of truth for every "no honest
// mtime available yet" fallback in this file: a doc page whose MDX file is missing,
// a catalog row whose updated_at does not parse, and any static path that somehow
// lacks a lastMod. Authors no longer land here — they take the newest updated_at of
// their own models. Update yearly while missing-MDX paths still need it.
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
}

interface CatalogResponse {
  items: CatalogModel[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number; // D-04: pagination cursor
}

// Rendered on request, not at build time.
//
// Without this, Next prerenders /sitemap.xml during `next build`. That build runs
// inside `docker build`, where the compose service `api` does not resolve, so the
// catalog fetch below threw, the catch swallowed it, and the XML was baked with
// only the static and docs entries — permanently, because a prerendered route is
// then served from disk.
//
// Measured 2026-08-26: jaot.io/sitemap.xml carried 78 URLs, all static or docs.
// Every one of the 103 marketplace model pages and every author page was missing.
// It looked correct locally because the local container runs the `dev` target,
// which renders per request and reaches the API.
//
// Cost is bounded: the catalog fetches below carry `revalidate: 3600`, so a burst
// of crawler requests shares one hourly walk of the catalog rather than repeating it.
export const dynamic = "force-dynamic";

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
  let authorEntries: MetadataRoute.Sitemap = [];

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
        // SSR_REQUEST_HEADERS: this walk is not a reader. Without it the API
        // banked one impression per listing on every pass — 103 an hour, 97.8%
        // of every impression it had ever stored.
        { next: { revalidate: 3600 }, headers: SSR_REQUEST_HEADERS }
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

    // Author profile entries from unique org IDs.
    //
    // lastModified is the newest `updated_at` among that author's own models. An
    // author page IS the list of their models, so it changes exactly when one of
    // them does — which is what <lastmod> is supposed to say.
    //
    // This used to read `author_created_at`, a field the catalog endpoint has
    // never returned, so every author fell through to the launch sentinel:
    // 2026-01-01 on every author page, for as long as the sitemap has existed.
    // A date that never moves tells a crawler nothing, and the same wrong date on
    // every URL is a signal Google can learn to ignore. The org's creation date
    // would not have fixed that either — it also never moves. The models do.
    //
    // The loop walks every catalog page (see the do/while above), so the maximum
    // here is over ALL of an author's models, not a page of them.
    //
    // WR-01: same id-sanitization guard for author orgIds — a malformed
    // author_organization_id would emit an unencoded /marketplace/authors/<bad> URL.
    // Map preserves first-insertion order, matching the previous ordering exactly.
    const orgLastModified = new Map<string, Date>();
    for (const model of models) {
      const orgId = model.author_organization_id;
      if (!orgId || !/^[A-Za-z0-9_-]+$/.test(orgId)) continue;
      const modelDate = safeDate(model.updated_at, FALLBACK_LAST_MODIFIED);
      const current = orgLastModified.get(orgId);
      if (!current || modelDate > current) {
        orgLastModified.set(orgId, modelDate);
      }
    }

    authorEntries = Array.from(orgLastModified, ([orgId, lastModified]) => ({
      url: `${BASE_URL}/marketplace/authors/${orgId}`,
      lastModified,
      changeFrequency: "weekly" as const,
      priority: 0.6,
      alternates: { languages: buildAlternates(`/marketplace/authors/${orgId}`) },
    }));
  } catch (err) {
    // Graceful degradation: return static + doc entries if backend is unreachable.
    // WR-04: log so a silently-empty catalog block (typo'd proxy URL, backend down,
    // mid-walk failure per CR-02) surfaces in SSR logs instead of only via a Google
    // Search Console alert days later.
    console.error("[sitemap] catalog/author block failed — emitting static + docs only", {
      error: err instanceof Error ? err.message : String(err),
    });
  }

  return [...staticEntries, ...docEntries, ...modelEntries, ...authorEntries];
}
