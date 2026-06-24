import { describe, it, expect, beforeEach, vi } from "vitest";
import { searchDocs, resetSearchIndex } from "../search-index";
import type { SearchEntry } from "../search-index";

const mockEntries: SearchEntry[] = [
  {
    id: 0,
    title: "Introduction",
    description: "Get started with JAOT optimization platform",
    slug: "getting-started/introduction",
    content: "Welcome to JAOT the multi-tenant optimization platform",
    section: "getting-started",
  },
  {
    id: 1,
    title: "Authentication",
    description: "Learn how to authenticate with the JAOT API",
    slug: "api/authentication",
    content: "JAOT supports API key authentication and JWT tokens",
    section: "api",
  },
  {
    id: 2,
    title: "First Solve",
    description: "Walk through your first optimization model",
    slug: "guides/first-solve",
    content: "This guide walks through creating and solving a linear programming problem",
    section: "guides",
  },
];

// Mock fetch to return our test data
globalThis.fetch = vi.fn().mockResolvedValue({
  json: () => Promise.resolve(mockEntries),
});

describe("searchDocs", () => {
  beforeEach(() => {
    resetSearchIndex();
    vi.clearAllMocks();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      json: () => Promise.resolve(mockEntries),
    });
  });

  it("returns empty results for empty query", async () => {
    const results = await searchDocs("");
    expect(results).toEqual([]);
  });

  it("returns empty results for whitespace-only query", async () => {
    const results = await searchDocs("   ");
    expect(results).toEqual([]);
  });

  it("returns results matching query in title", async () => {
    const results = await searchDocs("Authentication");
    expect(results.length).toBeGreaterThan(0);
    expect(results.some((r) => r.slug === "api/authentication")).toBe(true);
  });

  it("returns results matching query in content", async () => {
    const results = await searchDocs("optimization");
    expect(results.length).toBeGreaterThan(0);
  });

  it("returns results matching query in description", async () => {
    const results = await searchDocs("authenticate");
    expect(results.length).toBeGreaterThan(0);
    expect(results.some((r) => r.slug === "api/authentication")).toBe(true);
  });

  it("deduplicates results across fields", async () => {
    // "JAOT" appears in title, description, and content of multiple entries
    const results = await searchDocs("JAOT");
    const slugs = results.map((r) => r.slug);
    const uniqueSlugs = new Set(slugs);
    expect(slugs.length).toBe(uniqueSlugs.size);
  });

  it("returns no results for unmatched query", async () => {
    const results = await searchDocs("xyznonexistent");
    expect(results).toEqual([]);
  });

  it("fetches search index on first call", async () => {
    await searchDocs("test");
    expect(globalThis.fetch).toHaveBeenCalledWith("/search-index.json");
  });

  it("caches search index on subsequent calls", async () => {
    await searchDocs("first");
    await searchDocs("second");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});
