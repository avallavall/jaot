/**
 * /maintenance tells the truth about the site.
 *
 * Opened directly, the page said "Under Maintenance" to a visitor while the
 * site was up (browser QA, 2026-09-24). The proxy shows this page in place of
 * the one asked for while the site is in maintenance, and marks that request
 * with a header. A visit without the header is somebody who opened the address
 * by hand, and the page asks the API before saying the site is down.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

const { redirect, requestHeaders } = vi.hoisted(() => ({
  redirect: vi.fn(),
  requestHeaders: new Map<string, string>(),
}));

vi.mock("@/i18n/navigation", () => ({ redirect }));

vi.mock("next/headers", () => ({
  headers: async () => ({ get: (name: string) => requestHeaders.get(name) ?? null }),
}));

import MaintenancePage from "../page";
import { MAINTENANCE_REWRITE_HEADER } from "@/lib/maintenance";

const fetchMock = vi.fn();

function healthSays(maintenance: boolean) {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", maintenance }), { status: 200 }),
  );
}

async function visit(locale = "es") {
  render(await MaintenancePage({ params: Promise.resolve({ locale }) }));
}

describe("the maintenance page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requestHeaders.clear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // CONTRACT-TEST: /maintenance does not say the site is down when it is up
  it("sends a visitor to the home page when the site is not in maintenance", async () => {
    healthSays(false);

    await visit("es");

    expect(redirect).toHaveBeenCalledWith({ href: "/", locale: "es" });
  });

  it("stays when the site is in maintenance", async () => {
    healthSays(true);

    await visit();

    expect(redirect).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "maintenance.heading" })).toBeInTheDocument();
  });

  it("trusts the proxy that put it there, without asking again", async () => {
    requestHeaders.set(MAINTENANCE_REWRITE_HEADER, "1");

    await visit();

    // Asking again could disagree with the proxy's cached answer for a few
    // seconds, and a redirect home would then come straight back here.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(redirect).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "maintenance.heading" })).toBeInTheDocument();
  });

  it("treats an unreachable health check as a site that is up, as the proxy does", async () => {
    fetchMock.mockRejectedValue(new Error("connection refused"));

    await visit("en");

    expect(redirect).toHaveBeenCalledWith({ href: "/", locale: "en" });
  });
});
