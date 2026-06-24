import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

// Mock modules before importing component
vi.mock("@/lib/api", () => ({
  api: {
    getUserProfile: vi.fn().mockResolvedValue({
      id: "usr_test",
      name: "Test User",
      display_name: "Test User",
      slug: "test-user",
      organization_id: "org_test",
      organization_name: "Test Org",
      organization_verified: false,
      total_reviews: 0,
      avg_rating_given: 0,
      created_at: "2026-01-01T00:00:00Z",
    }),
    updateUserProfile: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "usr_test", name: "Test User", email: "test@test.com" },
    isAuthenticated: true,
  }),
}));

const mockSetSkillLevel = vi.fn().mockResolvedValue(undefined);
vi.mock("@/contexts/GuidanceContext", () => ({
  useGuidance: () => ({
    skillLevel: "beginner",
    setSkillLevel: mockSetSkillLevel,
    dismissedHints: [],
    dismissHint: vi.fn(),
    completedSteps: [],
    completeStep: vi.fn(),
    isStepCompleted: () => false,
    isHintDismissed: () => false,
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({
    showSuccess: vi.fn(),
    showError: vi.fn(),
    confirm: vi.fn(),
    DialogComponent: () => null,
  }),
}));

import MyProfilePage from "../my-profile/page";
import { toast } from "sonner";

describe("Guidance Preferences in My Profile", () => {
  beforeEach(() => {
    mockSetSkillLevel.mockClear();
    vi.mocked(toast.success).mockClear();
  });

  it("renders Guidance Preferences section", async () => {
    render(<MyProfilePage />);
    const heading = await screen.findByText("workspace.myProfile.guidancePreferences");
    expect(heading).toBeInTheDocument();
  });

  it("renders SkillLevelSelector with three options", async () => {
    render(<MyProfilePage />);
    await screen.findByText("workspace.myProfile.guidancePreferences");

    // Labels are now translation keys via the next-intl mock
    expect(screen.getByText("common.guidance.skillBeginner")).toBeInTheDocument();
    expect(screen.getByText("common.guidance.skillIntermediate")).toBeInTheDocument();
    expect(screen.getByText("common.guidance.skillExpert")).toBeInTheDocument();
  });

  it("calls setSkillLevel when a skill option is clicked", async () => {
    const user = userEvent.setup();
    render(<MyProfilePage />);
    await screen.findByText("workspace.myProfile.guidancePreferences");

    await user.click(screen.getByText("common.guidance.skillIntermediate"));
    expect(mockSetSkillLevel).toHaveBeenCalledWith("intermediate");
  });

  it("shows toast on skill level change", async () => {
    const user = userEvent.setup();
    render(<MyProfilePage />);
    await screen.findByText("workspace.myProfile.guidancePreferences");

    await user.click(screen.getByText("common.guidance.skillIntermediate"));
    expect(toast.success).toHaveBeenCalledWith("workspace.myProfile.skillLevelUpdated");
  });
});
