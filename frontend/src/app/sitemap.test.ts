// @vitest-environment node
// Node environment required: sitemap.ts uses fs + path (Node-only APIs).
// Patch global.localStorage so setup.tsx's afterEach does not crash in Node.
if (typeof global.localStorage === "undefined") {
  // Minimal stub — setup.tsx calls localStorage.clear(); this silences the crash.
  Object.defineProperty(global, "localStorage", {
    value: { clear: () => undefined, getItem: () => null, setItem: () => undefined },
    writable: true,
  });
}

import { describe, it, expect, vi } from "vitest";
import type { MetadataRoute } from "next";
import * as realFs from "fs";
import * as realPath from "path";

// CR-01: vi.mock MUST live at module top level — vitest hoists vi.mock above all
// imports so the registry is consulted as sitemap.ts resolves `import fs from "fs"`.
// sitemap.ts uses a DEFAULT import (`import fs from "fs"`), so we must override both
// the named `statSync` AND the `default.statSync` member for the mock to apply.
vi.mock("fs", async () => {
  const actual = await vi.importActual<typeof import("fs")>("fs");
  const statSync = vi.fn(() => ({ mtime: new Date("2026-03-15T00:00:00Z") }));
  return {
    ...actual,
    statSync,
    default: {
      ...actual,
      statSync,
    },
  };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const BASE_URL = "https://jaot.io";

type SitemapEntry = MetadataRoute.Sitemap[number];

function makePageResponse(
  items: object[],
  total: number,
  page: number,
  totalPages: number
) {
  return {
    ok: true,
    json: async () => ({ items, total, page, page_size: 100, total_pages: totalPages }),
  };
}

async function loadSitemapWithFetch(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  // CR-01: fs.statSync is mocked at module top level (see top of file). The hoisted
  // vi.mock factory genuinely satisfies sitemap.ts's `import fs from "fs"`, so every
  // doc entry gets the deterministic 2026-03-15 mtime regardless of process.cwd().
  vi.resetModules();
  const mod = await import("./sitemap");
  const entries: SitemapEntry[] = await mod.default();
  vi.unstubAllGlobals();
  return entries;
}

// ---------------------------------------------------------------------------
// Test 1 — Static entries with honest lastModified (D-06 static)
// ---------------------------------------------------------------------------
describe("sitemap", () => {
  it("static entries present with honest lastModified (not bare new Date)", async () => {
    const entries = await loadSitemapWithFetch(
      vi.fn().mockResolvedValue(makePageResponse([], 0, 1, 1))
    );

    const expectedStaticUrls = [
      BASE_URL, // home ("")
      `${BASE_URL}/for-sellers`,
      `${BASE_URL}/marketplace`,
      `${BASE_URL}/terms`,
      `${BASE_URL}/privacy`,
      `${BASE_URL}/licenses`,
    ];

    for (const expectedUrl of expectedStaticUrls) {
      const entry = entries.find((e) => e.url === expectedUrl);
      expect(entry, `Expected static entry for ${expectedUrl}`).toBeDefined();
      expect(entry!.lastModified).toBeInstanceOf(Date);
      // D-06: constants are pre-2026-06 (marketing: 2026-05-01, legal: 2026-01-01)
      // A bare new Date() would be "now" which would fail this check in future runs.
      const lm = entry!.lastModified instanceof Date
        ? entry!.lastModified
        : new Date(String(entry!.lastModified));
      expect(
        lm.getTime() < new Date("2026-06-01").getTime(),
        `lastModified for ${expectedUrl} must be a pre-2026-06-01 constant`
      ).toBe(true);
    }

    // WR-05: the intro slug must appear exactly once — emitted by the getDocsPages()
    // loop (D-05), never duplicated by a re-introduced hardcoded staticPages entry.
    // Split into two assertions: (1) the entry exists exactly once (a duplicate => 2 =>
    // fail), and (2) its lastModified is the mocked mtime — which proves CR-01's fs mock
    // is genuinely wired (it now is; the mock lives at module top level). Asserting the
    // concrete 2026-03-15 value catches a regression of the fs mock falling through to
    // the real on-disk mtime or the launch-sentinel fallback.
    const introEntries = entries.filter(
      (e) => e.url === `${BASE_URL}/docs/getting-started/introduction`
    );
    expect(
      introEntries,
      "intro slug must appear exactly once (from the getDocsPages() loop, never a hardcoded duplicate)"
    ).toHaveLength(1);

    const introLm =
      introEntries[0].lastModified instanceof Date
        ? introEntries[0].lastModified
        : new Date(String(introEntries[0].lastModified));
    expect(
      introLm,
      "intro entry must carry a lastModified Date"
    ).toBeInstanceOf(Date);
    expect(
      introLm.toISOString().startsWith("2026-03-15"),
      "intro lastModified must be the mocked statSync mtime (2026-03-15) — proves the fs mock applies (CR-01)"
    ).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Test 2 — Docs entries from getDocsPages() (D-05)
  // ---------------------------------------------------------------------------
  it("docs entries enumerated from getDocsPages() with correct count and known slug", async () => {
    const entries = await loadSitemapWithFetch(
      vi.fn().mockResolvedValue(makePageResponse([], 0, 1, 1))
    );

    const docEntries = entries.filter((e) => e.url.includes("/docs/"));

    expect(
      docEntries.length,
      "Expected at least 50 docs entries from getDocsPages()"
    ).toBeGreaterThanOrEqual(50);

    expect(
      docEntries.some((e) => e.url.endsWith("/docs/getting-started/introduction")),
      "getting-started/introduction slug must be present"
    ).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Test 3 — Pagination + updated_at consumption (D-04 + D-06 models)
  // ---------------------------------------------------------------------------
  it("model entries consume updated_at and paginate across two pages", async () => {
    const syntheticPage1Rest = Array.from({ length: 99 }, (_, i) => ({
      id: `m_synth_${i}`,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-02-01T00:00:00Z",
      author_organization_id: "org_bulk",
    }));

    const page1Items = [
      {
        id: "m1",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-04-15T00:00:00Z",
        author_organization_id: "org_a",
      },
      ...syntheticPage1Rest,
    ];

    const page2Items = [
      {
        id: "m101",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-05-20T00:00:00Z",
        author_organization_id: "org_b",
      },
    ];

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makePageResponse(page1Items, 101, 1, 2))
      .mockResolvedValueOnce(makePageResponse(page2Items, 101, 2, 2));

    const entries = await loadSitemapWithFetch(fetchMock);

    // Verify pagination: 2 catalog page calls
    const catalogCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).includes("/catalog")
    );
    expect(
      catalogCalls.length,
      "Expected 2 catalog fetch calls (one per page)"
    ).toBe(2);

    // Model entries = items with /marketplace/ but not /sellers/
    const modelEntries = entries.filter(
      (e) =>
        e.url.includes("/marketplace/") &&
        !e.url.includes("/marketplace/sellers/") &&
        !e.url.endsWith("/marketplace") &&
        !e.url.includes("/docs/")
    );
    expect(
      modelEntries.length,
      "Expected 101 model entries aggregated across both pages"
    ).toBe(101);

    // D-06: updated_at must be used, not created_at
    const m1 = modelEntries.find((e) => e.url.endsWith("/marketplace/m1"));
    expect(m1, "m1 entry must exist").toBeDefined();
    const m1Lm = m1!.lastModified instanceof Date
      ? m1!.lastModified
      : new Date(String(m1!.lastModified));
    expect(
      m1Lm.toISOString().startsWith("2026-04-15"),
      "m1 lastModified must be 2026-04-15 (updated_at), not 2026-01-01 (created_at)"
    ).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Test 4 — Every entry carries alternates.languages with x-default + 5 locales (SC2)
  // ---------------------------------------------------------------------------
  it("every entry carries alternates.languages with x-default and 5 locale keys", async () => {
    const entries = await loadSitemapWithFetch(
      vi.fn().mockResolvedValue(makePageResponse([], 0, 1, 1))
    );

    const expectedKeys = ["ca", "de", "en", "es", "fr", "x-default"];

    for (const entry of entries) {
      expect(
        entry.alternates?.languages,
        `Entry ${entry.url} must have alternates.languages`
      ).toBeDefined();
      const actualKeys = Object.keys(entry.alternates!.languages!).sort();
      expect(
        actualKeys,
        `Entry ${entry.url} must have exactly: ${expectedKeys.join(", ")}`
      ).toEqual(expectedKeys);
    }
  });

  // ---------------------------------------------------------------------------
  // Test 5 — Graceful degradation on catalog fetch failure
  // ---------------------------------------------------------------------------
  it("graceful degradation: static + docs entries emit even on catalog fetch failure", async () => {
    const entries = await loadSitemapWithFetch(
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) })
    );

    expect(entries.length, "Result must be non-empty on fetch failure").toBeGreaterThan(0);

    const modelEntries = entries.filter(
      (e) =>
        e.url.includes("/marketplace/") &&
        !e.url.includes("/marketplace/sellers/") &&
        !e.url.endsWith("/marketplace") &&
        !e.url.includes("/docs/")
    );
    expect(modelEntries.length, "No model entries on fetch failure").toBe(0);

    const sellerEntries = entries.filter((e) => e.url.includes("/sellers/"));
    expect(sellerEntries.length, "No seller entries on fetch failure").toBe(0);

    const docEntries = entries.filter((e) => e.url.includes("/docs/"));
    expect(
      docEntries.length,
      "Docs entries must still emit on catalog fetch failure"
    ).toBeGreaterThanOrEqual(50);
  });

  // ---------------------------------------------------------------------------
  // Test 6 — No bare new Date() in sitemap source (D-06 source-level check)
  // ---------------------------------------------------------------------------
  it("no bare new Date() lastModified in sitemap.ts source file", () => {
    const sitemapSource = realFs.readFileSync(
      realPath.join(__dirname, "sitemap.ts"),
      "utf8"
    );
    const hasBareNewDate = /lastModified:\s*new\s+Date\(\s*\)/.test(sitemapSource);
    expect(
      hasBareNewDate,
      "sitemap.ts must not contain bare `lastModified: new Date()` — use static constants"
    ).toBe(false);
  });
});
