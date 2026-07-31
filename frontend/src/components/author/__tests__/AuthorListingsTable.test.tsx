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

  it("does not offer a public link for an unlisted model either", () => {
    // is_public=false 404s on the catalog detail exactly like a withdrawal does,
    // so a link gated on status alone hands the author a dead page.
    render(
      <AuthorListingsTable
        listings={[row({ status: "published", is_public: false })]}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.queryByText("author.listings.viewPublic")).not.toBeInTheDocument();
  });

  it("always offers the edit link — it is where logos and screenshots live", () => {
    render(<AuthorListingsTable listings={[row()]} onChanged={vi.fn()} />);

    expect(screen.getByText("author.listings.edit").closest("a")).toHaveAttribute(
      "href",
      "/studio/mp_1/publish",
    );
  });

  it("renders a listing in a state the table does not special-case", () => {
    // The seeder retires templates as "deprecated" and the union did not cover it.
    // (The mocked translator answers `has` with true, so what this pins is that
    // the row renders at all; the message below is what stops a raw key showing.)
    render(
      <AuthorListingsTable
        listings={[row({ status: "deprecated" as AuthorListingRow["status"] })]}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByText("Vehicle routing")).toBeInTheDocument();
  });

  it("has a label for every listing state the database can hold", async () => {
    const messages = (await import("../../../../messages/en.json")).default;
    const labels = messages.author.listings.status;

    // draft | published | unpublished | deprecated — see ModelProjectListing.status
    // and app/shared/db/seed_models.py, which retires templates as deprecated.
    for (const state of ["draft", "published", "unpublished", "deprecated"]) {
      expect(labels, `no label for status "${state}"`).toHaveProperty(state);
    }
  });

  it("offers no withdraw button for a state the server would refuse", () => {
    render(
      <AuthorListingsTable
        listings={[row({ status: "deprecated" as AuthorListingRow["status"] })]}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "author.listings.withdraw" })).toBeNull();
    expect(screen.queryByRole("button", { name: "author.listings.restore" })).toBeNull();
  });

  it("says there are no ratings rather than showing a zero", () => {
    render(<AuthorListingsTable listings={[row({ avg_rating: null })]} onChanged={vi.fn()} />);

    expect(screen.getByText("author.listings.noRating")).toBeInTheDocument();
  });
});
