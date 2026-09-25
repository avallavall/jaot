/**
 * The proxy marks the requests it sends to the maintenance page.
 *
 * The page trusts the mark and shows itself. A request without it is
 * somebody who opened /maintenance by hand, and the page then asks the API
 * whether the site is down (see maintenance/__tests__/page.test.tsx).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { NextRequest } from "next/server";

// The locale middleware is not under test, and its ESM build cannot be loaded
// here. A request the maintenance check lets through reaches this stand-in.
vi.mock("next-intl/middleware", () => ({
  default: () => () => new Response(null, { status: 200 }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the proxy during maintenance", () => {
  it("rewrites a visitor to the maintenance page and marks the request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok", maintenance: true }), { status: 200 }),
      ),
    );
    const { default: proxy } = await import("../proxy");

    const res = await proxy(new NextRequest("http://localhost:3000/es/studio"));

    expect(new URL(res.headers.get("x-middleware-rewrite") ?? "").pathname).toBe(
      "/es/maintenance",
    );
    expect(res.headers.get("x-middleware-request-x-jaot-maintenance")).toBe("1");
  });
});
