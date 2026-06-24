/**
 * Marketplace model detail page (SSR) contract:
 *  - Unknown model (404) → real HTTP 404 via notFound() (audit F-04).
 *  - Existing model (200) → renders, no notFound().
 *  - Transient backend failure (429 / 5xx / network) → graceful degrade:
 *    the page still renders a 200 (client component loads the data) — NOT a
 *    hard 500 and NOT a spurious 404. The SSR fetch only feeds SEO metadata.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

const NOT_FOUND = new Error("NEXT_NOT_FOUND");
const notFoundMock = vi.fn(() => {
  throw NOT_FOUND;
});

vi.mock("next/navigation", () => ({
  notFound: () => notFoundMock(),
}));

// The client component pulls in the full api client — irrelevant here.
vi.mock("@/components/marketplace/ModelDetailClient", () => ({
  ModelDetailClient: () => null,
}));

import ModelDetailPage, { generateMetadata } from "../page";

const params = Promise.resolve({ locale: "en", modelId: "mdl_missing" });

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

describe("marketplace/[modelId] page (F-04)", () => {
  it("calls notFound() when the catalog returns 404", async () => {
    stubFetch({ ok: false, status: 404 });

    await expect(ModelDetailPage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("calls notFound() from generateMetadata for unknown models", async () => {
    stubFetch({ ok: false, status: 404 });

    await expect(generateMetadata({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("renders without notFound() when the model exists", async () => {
    stubFetch({
      ok: true,
      status: 200,
      json: async () => ({
        id: "mdl_1",
        display_name: "Fleet Routing",
        category: "logistics",
        price_eur: 49,
        total_activations: 10,
      }),
    } as unknown as Response);

    await expect(ModelDetailPage({ params })).resolves.toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  // CONTRACT-TEST: a rate-limited SSR fetch (429) must NOT become a 500 and must
  // NOT 404 — the page degrades to a 200 with the client component loading data.
  it("degrades to a 200 on 429 (no notFound, no throw)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch({ ok: false, status: 429 });

    await expect(ModelDetailPage({ params })).resolves.toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("degrades to a 200 on backend 5xx (no notFound, no throw)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch({ ok: false, status: 503 });

    await expect(ModelDetailPage({ params })).resolves.toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("degrades to a 200 on network failure (no notFound, no throw)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch(new Error("ECONNREFUSED"));

    await expect(ModelDetailPage({ params })).resolves.toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("generateMetadata returns generic metadata (no throw) on a transient failure", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch({ ok: false, status: 429 });

    const meta = await generateMetadata({ params });
    expect(meta).toBeTruthy();
    expect(notFoundMock).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
