/**
 * SC1/SC3 — SSR render verification
 *
 * This file runs in the lhci-gate CI step with NEXT_TEST_BASE_URL set
 * (Pitfall 7 from RESEARCH.md: SC3 must run after the standalone server is up,
 * not in the test-frontend step). It is the SC1+SC3 CI-gated check once the
 * gate drops failure:ignore in Plan 05.
 *
 * Usage:
 *   # CI (lhci-gate step, after `node .next/standalone/server.js &`):
 *   NEXT_TEST_BASE_URL=http://localhost:3000 npx vitest run src/lib/seo/__tests__/ssr-render.test.ts
 *
 *   # Local (standalone server must be running first):
 *   NEXT_TEST_BASE_URL=http://localhost:3000 npm run test -- --run src/lib/seo/__tests__/ssr-render.test.ts
 *
 *   # Plain `npm run test` — this block is skipped cleanly (0 tests run, 0 failures).
 */

import { describe, it, expect } from "vitest";

// fetch is global in Node 18+ and vitest — no import needed.

const BASE_URL = process.env.NEXT_TEST_BASE_URL;

interface RouteConfig {
  path: string;
  /** strict: asserts exactly-one <h1> + no skipped heading levels */
  strict: boolean;
}

// Dynamic pages (marketplace, marketplace/[id]) need backend+DB to render —
// excluded from this test per D-01 (dynamic pages stay post-deploy-live).
const PUBLIC_ROUTES: RouteConfig[] = [
  { path: "/en", strict: true },
  { path: "/en/pricing", strict: true },
  { path: "/en/contact", strict: true },
  // OR-01 resolved POSITIVE (Plan 03, 2026-06-08): docs/[...slug]/page.tsx is a Server
  // Component (no "use client" at page level); MDX is server-rendered via @next/mdx +
  // rehype-slug. fetch() follows the locale 307 redirect (as-needed prefix strips /en/)
  // and the final HTML contains exactly one <h1 id="introduction"> from the MDX "# Introduction"
  // heading. Upgraded to strict — docs participates in the same CI h1-count assertion.
  { path: "/en/docs/getting-started/introduction", strict: true },
];

describe.skipIf(!BASE_URL)("SC1/SC3 — SSR render verification (requires next start)", () => {
  for (const route of PUBLIC_ROUTES) {
    if (route.strict) {
      it(`${route.path} — renders exactly one <h1> in raw HTML, no skipped heading levels`, async () => {
        const res = await fetch(`${BASE_URL}${route.path}`);
        expect(res.status).toBe(200);
        const html = await res.text();

        // SEO-11: exactly one <h1> per page (proves Server Component render)
        const h1Matches = html.match(/<h1[\s>]/gi) ?? [];
        expect(h1Matches.length).toBe(1);

        // No skipped heading levels: for each hN present, h(N-1) must also be present
        // e.g. h3→h2, h4→h3, h5→h4, h6→h5 — catches gaps like h2→h4 too
        const levels = [2, 3, 4, 5, 6];
        for (let i = 1; i < levels.length; i++) {
          if (new RegExp(`<h${levels[i]}[\\s>]`, "i").test(html)) {
            expect(new RegExp(`<h${levels[i - 1]}[\\s>]`, "i").test(html)).toBe(true);
          }
        }
      });
    } else {
      it(`${route.path} — lenient check (status 200, non-empty HTML, pending OR-01)`, async () => {
        // OR-01: Plan 03 confirms whether docs MDX H1 is in SSR HTML; upgrade to strict or exclude with rationale.
        const res = await fetch(`${BASE_URL}${route.path}`);
        expect(res.status).toBe(200);
        const html = await res.text();
        expect(html.length).toBeGreaterThan(0);
      });
    }
  }
});
