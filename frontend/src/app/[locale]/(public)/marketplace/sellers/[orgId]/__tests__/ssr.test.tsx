/**
 * Seller profile page (SSR) contract — mirrors the model page:
 *  - Unknown seller (404) → real HTTP 404 via notFound().
 *  - Existing seller (200) → renders, no notFound().
 *  - Transient backend failure (429 / 5xx / network) → graceful degrade to a
 *    200; previously a 429 here turned a live seller into a spurious 404.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

const NOT_FOUND = new Error("NEXT_NOT_FOUND");
const notFoundMock = vi.fn(() => {
  throw NOT_FOUND;
});

vi.mock("next/navigation", () => ({
  notFound: () => notFoundMock(),
}));

vi.mock("@/components/marketplace/SellerProfileClient", () => ({
  SellerProfileClient: () => null,
}));

import SellerProfilePage, { generateMetadata } from "../page";

const params = Promise.resolve({ locale: "en", orgId: "org_x" });

function stubFetch(response: Partial<Response> | Error) {
  const impl =
    response instanceof Error
      ? vi.fn(async () => {
          throw response;
        })
      : vi.fn(async () => response as Response);
  vi.stubGlobal("fetch", impl);
  return impl;
}

afterEach(() => {
  vi.unstubAllGlobals();
  notFoundMock.mockClear();
});

describe("marketplace/sellers/[orgId] page (SSR)", () => {
  it("calls notFound() when the profile returns 404", async () => {
    stubFetch({ ok: false, status: 404 });

    await expect(SellerProfilePage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("renders without notFound() when the seller exists", async () => {
    stubFetch({
      ok: true,
      status: 200,
      json: async () => ({ id: "org_x", name: "Acme Optimization" }),
    } as unknown as Response);

    await expect(SellerProfilePage({ params })).resolves.toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  // CONTRACT-TEST: a transient 429 must not de-index a live seller — degrade to 200.
  it("degrades to a 200 on 429 (no spurious 404)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch({ ok: false, status: 429 });

    await expect(SellerProfilePage({ params })).resolves.toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("generateMetadata does not throw on a transient failure", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch({ ok: false, status: 503 });

    const meta = await generateMetadata({ params });
    expect(meta).toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
