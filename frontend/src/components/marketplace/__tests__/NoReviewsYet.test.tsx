/**
 * The author of a model is not invited to review it.
 *
 * On their own listing with no reviews, the author read "You published this
 * model, so you cannot review it" and, under it, "No reviews yet. Be the first
 * to review this model!" (browser QA, 2026-09-24).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const { getCatalogModel, getCatalogReviews, getFavorites, auth } = vi.hoisted(() => ({
  getCatalogModel: vi.fn(),
  getCatalogReviews: vi.fn(),
  getFavorites: vi.fn(),
  auth: {
    isAuthenticated: true,
    organization: { id: "org_author" } as { id: string } | null,
  },
}));

vi.mock("@/lib/api", () => ({
  api: { getCatalogModel, getCatalogReviews, getFavorites },
}));

vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({ DialogComponent: () => null, showError: vi.fn() }),
}));

vi.mock("@/components/marketplace/ModelTabs", () => ({ ModelTabs: () => null }));
vi.mock("@/components/marketplace/ImageGallery", () => ({ ImageGallery: () => null }));

import { ModelDetailClient } from "../ModelDetailClient";

const MODEL = {
  id: "cat_facility",
  name: "facility",
  display_name: "Facility Location",
  description: "Open plants and ship to stores.",
  category: "logistics",
  tags: [],
  version: "1.0.0",
  is_official: false,
  is_featured: false,
  total_activations: 0,
  total_executions: 0,
  author_organization_id: "org_author",
  author_name: "Author Org",
  author_verified: false,
  created_at: "2026-09-24T10:00:00Z",
  updated_at: "2026-09-24T10:00:00Z",
};

describe("a listing with no reviews yet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getCatalogModel.mockResolvedValue(MODEL);
    getCatalogReviews.mockResolvedValue({ items: [], total: 0 });
    getFavorites.mockResolvedValue([]);
  });

  // CONTRACT-TEST: the author is never invited to review their own model
  it("does not invite its author to be the first reviewer", async () => {
    auth.organization = { id: "org_author" };

    render(<ModelDetailClient modelId="cat_facility" />);

    expect(
      await screen.findByText("marketplace.detail.cannotReviewOwnModel"),
    ).toBeInTheDocument();
    expect(screen.getByText("marketplace.detail.noReviewsOwnModel")).toBeInTheDocument();
    expect(screen.queryByText("marketplace.detail.noReviews")).toBeNull();
  });

  it("invites anybody else to be the first reviewer", async () => {
    auth.organization = { id: "org_reader" };

    render(<ModelDetailClient modelId="cat_facility" />);

    expect(await screen.findByText("marketplace.detail.noReviews")).toBeInTheDocument();
    expect(screen.queryByText("marketplace.detail.noReviewsOwnModel")).toBeNull();
  });
});
