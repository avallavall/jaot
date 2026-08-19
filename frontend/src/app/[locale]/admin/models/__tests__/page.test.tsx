import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { request: apiRequest },
}));

import ModelsPage from "../page";

const listing = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  name: id,
  display_name: "Listing " + id,
  description: "A listing",
  category: "general",
  version: "1.0.0",
  is_official: false,
  is_featured: false,
  is_public: true,
  created_at: "2026-08-01T00:00:00Z",
  ...over,
});

/** The shape the admin API really answers with: `pages`, not `total_pages`. */
const answer = (items: unknown[], total: number, pages: number) => ({
  items,
  total,
  page: 1,
  page_size: 20,
  pages,
});

describe("Admin models page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // CONTRACT-Test is a backend annotation; here the guard is the field name.
  // The page read `total_pages`, which the admin API never sends, so it fell
  // back to one page and hid its own paging buttons: an admin saw 20 of 102
  // listings and had no way to reach the rest.
  it("shows the paging buttons when the answer has more than one page", async () => {
    apiRequest.mockResolvedValue(answer([listing("mdl_1")], 102, 6));

    render(<ModelsPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "common.next" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "common.previous" })).toBeInTheDocument();
  });

  it("keeps the paging buttons away when everything fits on one page", async () => {
    apiRequest.mockResolvedValue(answer([listing("mdl_1")], 1, 1));

    render(<ModelsPage />);

    await waitFor(() => expect(apiRequest).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "common.next" })).not.toBeInTheDocument();
  });

  it("sends the typed term to the server as a search parameter", async () => {
    apiRequest.mockResolvedValue(answer([listing("mdl_1")], 1, 1));

    render(<ModelsPage />);
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());

    await userEvent.type(
      screen.getByPlaceholderText("admin.models.searchPlaceholder"),
      "route",
    );

    await waitFor(() => {
      const urls = apiRequest.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes("search=route"))).toBe(true);
    });
  });

  it("tells an on badge from an off one without using colour", async () => {
    apiRequest.mockResolvedValue(
      answer([listing("mdl_1", { is_official: true, is_featured: false })], 1, 1),
    );

    render(<ModelsPage />);

    const official = await screen.findByRole("button", { name: /admin\.models\.official/ });
    const featured = await screen.findByRole("button", { name: /admin\.models\.featured/ });

    expect(official).toHaveAttribute("aria-pressed", "true");
    expect(featured).toHaveAttribute("aria-pressed", "false");
    // the tick is the cue a reader who cannot separate the two backgrounds sees
    expect(official.querySelector("svg")).not.toBeNull();
    expect(featured.querySelector("svg")).toBeNull();
  });
});
