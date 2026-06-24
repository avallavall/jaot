/**
 * Vitest unit tests for robots.ts (SC1 shape contract).
 *
 * Asserts the MetadataRoute.Robots return value shape: disallow list completeness (D-01),
 * AI bot allow-list completeness and Bytespider exclusion (D-03), no crawlDelay (D-02),
 * and correct sitemap href. These regression guards catch silent removals at PR time
 * (< 30s feedback, before the slower Wave-3 Playwright E2E gate).
 */
import { describe, it, expect } from "vitest";
import robots from "./robots";

describe("robots.ts (SC1 shape contract)", () => {
  it("returns MetadataRoute.Robots with rules array + sitemap reference", () => {
    const result = robots();
    expect(Array.isArray(result.rules)).toBe(true);
    expect(typeof result.sitemap).toBe("string");
    expect((result.sitemap as string).endsWith("/sitemap.xml")).toBe(true);
  });

  it("wildcard rule covers D-01 extensivo disallow list", () => {
    const result = robots();
    const rules = result.rules as Array<{
      userAgent: string | string[];
      disallow?: string | string[];
    }>;

    const wildcardRule = rules.find((r) => r.userAgent === "*");
    expect(wildcardRule).toBeDefined();
    expect(Array.isArray(wildcardRule!.disallow)).toBe(true);

    const disallow = wildcardRule!.disallow as string[];

    // REQ baseline (D-01) — private API + app surfaces
    expect(disallow).toContain("/api/");
    expect(disallow).toContain("/admin/");
    expect(disallow).toContain("/builder/");
    expect(disallow).toContain("/solve/");
    expect(disallow).toContain("/triggers/");
    expect(disallow).toContain("/workspace/");
    expect(disallow).toContain("/billing/");

    // Real auth + org + maintenance pages (D-01 extensivo)
    // NOTE: SEO-02 listed /[locale]/auth/ — that route does NOT exist.
    // Real auth pages are the individual routes below. See robots.ts inline comment.
    expect(disallow).toContain("/login");
    expect(disallow).toContain("/signup");
    expect(disallow).toContain("/forgot-password");
    expect(disallow).toContain("/reset-password");
    expect(disallow).toContain("/join/");
    expect(disallow).toContain("/org/");
    expect(disallow).toContain("/maintenance");

    // Locale-prefixed variants (D-01 defense-in-depth)
    expect(disallow).toContain("/*/login");
    expect(disallow).toContain("/*/signup");
    expect(disallow).toContain("/*/forgot-password");
    expect(disallow).toContain("/*/reset-password");
    expect(disallow).toContain("/*/join/");
    expect(disallow).toContain("/*/org/");
    expect(disallow).toContain("/*/maintenance");
  });

  it("AI bot allow-list contains D-03s 8 bots and EXCLUDES Bytespider", () => {
    const result = robots();
    const rules = result.rules as Array<{ userAgent: string | string[] }>;

    const userAgents = rules.map((r) => r.userAgent);

    // D-03: exactly the 8 permitted AI bots
    expect(userAgents).toContain("GPTBot");
    expect(userAgents).toContain("ClaudeBot");
    expect(userAgents).toContain("Google-Extended");
    expect(userAgents).toContain("PerplexityBot");
    expect(userAgents).toContain("CCBot");
    expect(userAgents).toContain("OAI-SearchBot");
    expect(userAgents).toContain("AppleBot-Extended");
    expect(userAgents).toContain("Meta-ExternalAgent");

    // D-03 explicit skip: Bytespider must NOT appear as a userAgent in any rule
    // (it may only appear inside a comment in the source file, which this runtime
    // test cannot see — and that is intentional)
    expect(userAgents.every((ua) => ua !== "Bytespider")).toBe(true);
  });

  it("no crawlDelay emitted (D-02 discretion)", () => {
    const result = robots();
    const rules = result.rules as Array<{ crawlDelay?: number }>;
    for (const rule of rules) {
      expect(rule.crawlDelay).toBeUndefined();
    }
  });

  it("sitemap directive points to BASE_URL + /sitemap.xml", () => {
    const result = robots();
    const expectedBase = process.env.NEXT_PUBLIC_SITE_URL || "https://jaot.io";
    expect(result.sitemap).toBe(`${expectedBase}/sitemap.xml`);
  });
});
