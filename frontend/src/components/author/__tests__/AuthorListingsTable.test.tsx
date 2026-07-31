import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import type { AuthorListingRow } from "@/lib/types";

const { unpublishModelProject, republishModelProject } = vi.hoisted(() => ({
  unpublishModelProject: vi.fn(),
  republishModelProject: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { unpublishModelProject, republishModelProject },
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { AuthorListingsTable } from "../AuthorListingsTable";

const row = (over: Partial<AuthorListingRow> = {}): AuthorListingRow => ({
  model_project_id: "mp_1",
  display_name: "Vehicle routing",
  short_description: "Deliveries",
  category: "logistics",
  status: "published",
  is_public: true,
  version: "1.0.0",
  logo_url: null,
  total_activations: 3,
  total_executions: 12,
  avg_rating: null,
  success_rate: null,
  published_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-30T00:00:00Z",
  ...over,
});

describe("AuthorListingsTable", () => {
  beforeEach(() => vi.clearAllMocks());

  it("points a brand-new author at the studio instead of showing an empty table", () => {
    render(<AuthorListingsTable listings={[]} onChanged={vi.fn()} />);

    expect(screen.getByText("author.listings.emptyTitle")).toBeInTheDocument();
    expect(screen.getByText("author.listings.emptyCta").closest("a")).toHaveAttribute(
      "href",
      "/studio",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("withdraws a published listing and flips the action to publish again", async () => {
    unpublishModelProject.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<AuthorListingsTable listings={[row()]} onChanged={onChanged} />);

    await userEvent.click(screen.getByRole("button", { name: "author.listings.withdraw" }));

    await waitFor(() => expect(unpublishModelProject).toHaveBeenCalledWith("mp_1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "unpublished" }));
  });

  it("restores a withdrawn listing", async () => {
    republishModelProject.mockResolvedValue({});
    const onChanged = vi.fn();
    render(
      <AuthorListingsTable listings={[row({ status: "unpublished" })]} onChanged={onChanged} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "author.listings.restore" }));

    await waitFor(() => expect(republishModelProject).toHaveBeenCalledWith("mp_1"));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "published" }));
  });

  it("does not offer a public link for something that is not public", () => {
    render(
      <AuthorListingsTable listings={[row({ status: "unpublished" })]} onChanged={vi.fn()} />,
    );

    expect(screen.queryByText("author.listings.viewPublic")).not.toBeInTheDocument();
  });

  it("says there are no ratings rather than showing a zero", () => {
    render(<AuthorListingsTable listings={[row({ avg_rating: null })]} onChanged={vi.fn()} />);

    expect(screen.getByText("author.listings.noRating")).toBeInTheDocument();
  });
});
