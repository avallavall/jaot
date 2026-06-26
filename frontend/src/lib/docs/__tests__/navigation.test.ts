import { describe, it, expect } from "vitest";
import { getFlatPages, getPrevNext, getDocsPages } from "../navigation";

describe("getFlatPages", () => {
  it("returns all leaf pages with guides included", () => {
    const pages = getFlatPages();
    // 3 getting-started + 5 ai-builder + 2 marketplace + 1 mcp + 12 api + 2 reference + 35 guides = 60
    expect(pages.length).toBe(60);
    expect(pages[0].slug).toBe("getting-started/introduction");
  });

  it("includes guide pages", () => {
    const pages = getFlatPages();
    const guideSlugs = pages.filter((p) => p.slug.startsWith("guides/"));
    expect(guideSlugs.length).toBe(35);
  });

  it("contains no duplicate slugs", () => {
    const pages = getFlatPages();
    const slugs = pages.map(p => p.slug);
    const uniqueSlugs = new Set(slugs);
    expect(slugs.length).toBe(uniqueSlugs.size);
  });
});

describe("getPrevNext", () => {
  it("returns null prev for first page", () => {
    const { prev, next } = getPrevNext("getting-started/introduction");
    expect(prev).toBeNull();
    expect(next).not.toBeNull();
  });

  it("returns null next for last page", () => {
    const pages = getFlatPages();
    const lastSlug = pages[pages.length - 1].slug;
    const { next } = getPrevNext(lastSlug);
    expect(next).toBeNull();
  });

  it("returns correct prev/next for middle pages", () => {
    const pages = getFlatPages();
    const midSlug = pages[1].slug;
    const { prev, next } = getPrevNext(midSlug);
    expect(prev!.slug).toBe(pages[0].slug);
    expect(next!.slug).toBe(pages[2].slug);
  });
});

describe("getDocsPages", () => {
  it("returns same result as getFlatPages", () => {
    expect(getDocsPages()).toEqual(getFlatPages());
  });
});
