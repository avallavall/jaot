import { describe, it, expect, vi, afterEach } from "vitest";
import { ssrJsonFetch } from "../ssrFetch";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ssrJsonFetch", () => {
  it("returns ok with parsed data on 200", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, { id: "x" })));

    const result = await ssrJsonFetch<{ id: string }>("http://api/x");

    expect(result).toEqual({ status: "ok", data: { id: "x" } });
  });

  it("returns notFound on 404 (no retry)", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(404, null));
    vi.stubGlobal("fetch", fetchMock);

    const result = await ssrJsonFetch("http://api/x", { retries: 2 });

    expect(result).toEqual({ status: "notFound" });
    expect(fetchMock).toHaveBeenCalledTimes(1); // 404 is terminal, not retried
  });

  it("returns unavailable on persistent 429 after retries", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchMock = vi.fn(async () => jsonResponse(429, null));
    vi.stubGlobal("fetch", fetchMock);

    const result = await ssrJsonFetch("http://api/x", { retries: 2, backoffMs: 1 });

    expect(result).toEqual({ status: "unavailable" });
    expect(fetchMock).toHaveBeenCalledTimes(3); // initial + 2 retries
  });

  it("recovers when a transient failure is followed by a 200", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(503, null))
      .mockResolvedValueOnce(jsonResponse(200, { id: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await ssrJsonFetch<{ id: string }>("http://api/x", {
      retries: 2,
      backoffMs: 1,
    });

    expect(result).toEqual({ status: "ok", data: { id: "ok" } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns unavailable on network rejection (never throws)", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );

    const result = await ssrJsonFetch("http://api/x", { retries: 1, backoffMs: 1 });

    expect(result).toEqual({ status: "unavailable" });
  });

  it("returns unavailable (not ok) when JSON parsing fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError("Unexpected token");
        },
      })) as unknown as typeof fetch,
    );

    const result = await ssrJsonFetch("http://api/x", { retries: 0 });

    expect(result).toEqual({ status: "unavailable" });
  });

  it("does not retry a non-transient 4xx (e.g. 400)", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchMock = vi.fn(async () => jsonResponse(400, null));
    vi.stubGlobal("fetch", fetchMock);

    const result = await ssrJsonFetch("http://api/x", { retries: 2, backoffMs: 1 });

    expect(result).toEqual({ status: "unavailable" });
    expect(fetchMock).toHaveBeenCalledTimes(1); // 400 is a client error, not retried
  });
});
