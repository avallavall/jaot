/**
 * "What I Publish" keeps its author checklist in step with the listings.
 *
 * Withdraw and "Publish again" change the listing on the same page, and the
 * "Get set up as an author" checklist kept the state it loaded with. After
 * withdrawing the only published model, "Publish your first model" still read
 * as done (browser QA, 2026-09-24).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const {
  getAuthorListings,
  getAuthorOnboardingStatus,
  unpublishModelProject,
  republishModelProject,
} = vi.hoisted(() => ({
  getAuthorListings: vi.fn(),
  getAuthorOnboardingStatus: vi.fn(),
  unpublishModelProject: vi.fn(),
  republishModelProject: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getAuthorListings,
    getAuthorOnboardingStatus,
    unpublishModelProject,
    republishModelProject,
  },
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/components/author/AuthorAnalyticsPanel", () => ({ AuthorAnalyticsPanel: () => null }));
vi.mock("@/components/author/AuthorReviewsList", () => ({ AuthorReviewsList: () => null }));

import AuthorModelsPage from "../models/page";

const ROW = {
  model_project_id: "mp_facility",
  display_name: "Facility",
  short_description: null,
  category: "logistics",
  status: "published",
  is_public: true,
  version: "1",
  logo_url: null,
  total_activations: 0,
  total_executions: 0,
  avg_rating: null,
  success_rate: null,
  published_at: "2026-09-24T10:00:00Z",
  updated_at: "2026-09-24T10:00:00Z",
};

function status(published: boolean) {
  return {
    all_complete: false,
    steps: [
      { key: "complete_profile", completed: false, link: "/workspace/profile" },
      { key: "publish_model", completed: published, link: "/studio" },
      { key: "add_rich_media", completed: false, link: "/workspace/models" },
    ],
  };
}

describe("the author checklist on What I Publish", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAuthorListings.mockResolvedValue([ROW]);
    unpublishModelProject.mockResolvedValue(undefined);
    republishModelProject.mockResolvedValue(undefined);
  });

  // CONTRACT-TEST: the checklist follows a withdraw made on the same page
  it("asks the server again after a listing is withdrawn", async () => {
    getAuthorOnboardingStatus
      .mockResolvedValueOnce(status(true))
      .mockResolvedValueOnce(status(false));
    const user = userEvent.setup();
    render(<AuthorModelsPage />);

    const publishStep = await screen.findByText("author.onboarding.steps.publish_model.title");
    // Done: struck through, no call to action.
    expect(publishStep.className).toMatch(/line-through/);

    await user.click(await screen.findByRole("button", { name: "author.listings.withdraw" }));

    await waitFor(() => expect(getAuthorOnboardingStatus).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.getByText("author.onboarding.steps.publish_model.title").className,
      ).not.toMatch(/line-through/),
    );
  });

  it("asks the server again after a listing is published again", async () => {
    getAuthorListings.mockResolvedValue([{ ...ROW, status: "unpublished" }]);
    getAuthorOnboardingStatus
      .mockResolvedValueOnce(status(false))
      .mockResolvedValueOnce(status(true));
    const user = userEvent.setup();
    render(<AuthorModelsPage />);

    await user.click(await screen.findByRole("button", { name: "author.listings.restore" }));

    await waitFor(() => expect(getAuthorOnboardingStatus).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.getByText("author.onboarding.steps.publish_model.title").className,
      ).toMatch(/line-through/),
    );
  });
});
