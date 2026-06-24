import { test, expect } from "@playwright/test";

// D-11: CI build only — runs against prod Docker build (target: runner), NOT npm run dev.
// No auth setup, no mocking — hits real SSR'd HTML (per integration_proof.md Phase 11 policy).
// Wave-0 proving harness: spec is registered now; goes GREEN after Plan 04 wires the routes.

const BASE_URL = process.env.BASE_URL || "https://jaot.io";

// Resolve a real model id from the public catalog API (no auth). Returns null when the
// catalog is unavailable or empty so callers can test.skip() with a clear reason.
async function resolveModelId(
  request: import("@playwright/test").APIRequestContext,
): Promise<string | null> {
  const resp = await request.get(`${BASE_URL}/api/v2/models/catalog`);
  if (resp.status() !== 200) return null;
  const catalog = (await resp.json()) as { items?: Array<{ id: string }> };
  return catalog.items?.[0]?.id ?? null;
}

// Helper: collect all parsed JSON-LD objects from a page.
// Collects every <script type="application/ld+json"> textContent and JSON.parses them.
async function getJsonLds(page: import("@playwright/test").Page) {
  const scripts = await page
    .locator('script[type="application/ld+json"]')
    .all();
  const texts = await Promise.all(scripts.map((s) => s.textContent()));
  return texts
    .filter((t): t is string => t !== null)
    .map((t) => JSON.parse(t) as Record<string, unknown>);
}

test.describe("SEO structured data: JSON-LD per route", () => {
  test("home page emits Organization JSON-LD with name JAOT", async ({
    page,
  }) => {
    await page.goto("/");
    const jsonLds = await getJsonLds(page);
    const org = jsonLds.find((j) => j["@type"] === "Organization");
    expect(org).toBeDefined();
    expect(org!.name).toBe("JAOT");
  });

  test(
    "home page emits WebSite JSON-LD with SearchAction targeting ?search= (not ?q=)",
    async ({ page }) => {
      await page.goto("/");
      const jsonLds = await getJsonLds(page);
      const website = jsonLds.find((j) => j["@type"] === "WebSite");
      expect(website).toBeDefined();
      const action = website!.potentialAction as Record<string, unknown>;
      expect(action).toBeDefined();
      const target = String(action.target ?? "");
      expect(target).toContain("?search=");
      expect(target).not.toContain("?q=");
    },
  );

  test("marketplace listing emits Product JSON-LD with offers and brand", async ({
    page,
    request,
  }) => {
    const modelId = await resolveModelId(request);
    if (!modelId) {
      console.warn(`[seo-structured-data] skipping marketplace assertions: could not resolve a model id from ${BASE_URL}`);
      test.skip(true, "Catalog API unavailable or empty — no model id to navigate to");
      return;
    }
    await page.goto(`/marketplace/${modelId}`);
    const jsonLds = await getJsonLds(page);
    const product = jsonLds.find((j) => j["@type"] === "Product");
    expect(product).toBeDefined();
    // offers must be present
    expect(product!.offers).toBeDefined();
    // brand must be present
    expect(product!.brand).toBeDefined();
  });

  test("marketplace listing has no AggregateRating in JSON-LD (SC4 policy)", async ({
    page,
    request,
  }) => {
    const modelId = await resolveModelId(request);
    if (!modelId) {
      console.warn(`[seo-structured-data] skipping marketplace assertions: could not resolve a model id from ${BASE_URL}`);
      test.skip(true, "Catalog API unavailable or empty — no model id to navigate to");
      return;
    }
    await page.goto(`/marketplace/${modelId}`);
    const jsonLds = await getJsonLds(page);
    // No JSON-LD object should have @type "AggregateRating"
    const aggRating = jsonLds.find((j) => j["@type"] === "AggregateRating");
    expect(aggRating).toBeUndefined();
    // No JSON-LD object should carry an aggregateRating key
    for (const ld of jsonLds) {
      expect(Object.prototype.hasOwnProperty.call(ld, "aggregateRating")).toBe(false);
    }
  });

  test(
    "docs page emits BreadcrumbList JSON-LD at /docs/getting-started/introduction",
    async ({ page }) => {
      await page.goto("/docs/getting-started/introduction");
      const jsonLds = await getJsonLds(page);
      const breadcrumb = jsonLds.find((j) => j["@type"] === "BreadcrumbList");
      expect(breadcrumb).toBeDefined();
      // The breadcrumb path /docs/getting-started/introduction has 3 segments:
      // docs, getting-started, introduction → expect exactly 3 items.
      const items = breadcrumb!.itemListElement as unknown[];
      expect(Array.isArray(items)).toBe(true);
      expect(items.length).toBe(3);
    },
  );
});

test.describe("SEO llms.txt availability", () => {
  test("GET /llms.txt returns 200 with # JAOT header (SC5)", async ({
    request,
  }) => {
    const resp = await request.get("/llms.txt");
    expect(resp.status()).toBe(200);
    const text = await resp.text();
    expect(text).toContain("# JAOT");
  });

  test("GET /.well-known/llms.txt 301-redirects to canonical /llms.txt (SC5)", async ({
    request,
  }) => {
    // The backend's pre-existing .well-known/llms.txt now permanently redirects
    // to the single canonical root document (Phase 13.3 D-09). Crawlers must
    // converge on /llms.txt rather than two divergent copies.
    const resp = await request.get("/.well-known/llms.txt", {
      maxRedirects: 0,
    });
    expect(resp.status()).toBe(301);
    expect(resp.headers()["location"]).toContain("/llms.txt");
  });

  test("GET a typo'd llms path returns 404 (SC5 deliberate misroute check)", async ({
    request,
  }) => {
    const resp = await request.get("/.well-known/llms-typo.txt");
    expect(resp.status()).toBe(404);
  });
});
