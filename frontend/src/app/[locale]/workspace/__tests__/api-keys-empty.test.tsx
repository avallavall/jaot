import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const mockGetKeys = vi.fn().mockResolvedValue([]);
const mockCreateKey = vi.fn();
const mockDeleteKey = vi.fn();

// Mock api to return empty keys by default
vi.mock("@/lib/api", () => ({
  api: {
    getKeys: (...args: unknown[]) => mockGetKeys(...args),
    createKey: (...args: unknown[]) => mockCreateKey(...args),
    deleteKey: (...args: unknown[]) => mockDeleteKey(...args),
  },
}));

vi.mock("@/contexts/GuidanceContext", () => ({
  useGuidance: () => ({
    skillLevel: "beginner",
    setSkillLevel: vi.fn(),
    dismissedHints: [],
    dismissHint: vi.fn(),
    completedSteps: [],
    completeStep: vi.fn(),
    isStepCompleted: () => false,
    isHintDismissed: () => false,
  }),
}));

vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({
    showSuccess: vi.fn(),
    showError: vi.fn(),
    confirm: vi.fn().mockResolvedValue(true),
    DialogComponent: () => null,
  }),
}));

import ClientAPIKeysPage from "../api-keys/page";

describe("API Keys EmptyState", () => {
  beforeEach(() => {
    mockGetKeys.mockReset().mockResolvedValue([]);
    mockCreateKey.mockReset();
    mockDeleteKey.mockReset();
  });

  it("shows EmptyState when no keys exist", async () => {
    render(<ClientAPIKeysPage />);
    const title = await screen.findByText("workspace.apiKeys.noKeysTitle");
    expect(title).toBeInTheDocument();
  });

  it("shows beginner description by default", async () => {
    render(<ClientAPIKeysPage />);
    const description = await screen.findByText("workspace.apiKeys.noKeysDescription");
    expect(description).toBeInTheDocument();
  });

  it("shows Create your first API key CTA", async () => {
    render(<ClientAPIKeysPage />);
    const cta = await screen.findByRole("button", { name: /workspace\.apiKeys\.createFirstKey/i });
    expect(cta).toBeInTheDocument();
  });

  it("CTA opens create dialog", async () => {
    const user = userEvent.setup();
    render(<ClientAPIKeysPage />);
    const cta = await screen.findByRole("button", { name: /workspace\.apiKeys\.createFirstKey/i });

    await user.click(cta);

    // The create key dialog should be open with the key name label (translation key)
    await waitFor(() => {
      expect(screen.getByLabelText("workspace.apiKeys.keyName")).toBeInTheDocument();
    });
  });

  it("does not show EmptyState when keys exist", async () => {
    mockGetKeys.mockResolvedValue([
      {
        id: "key_1",
        name: "Test Key",
        key_prefix: "ok_live_abc",
        is_active: true,
        created_at: "2026-01-01",
        last_used_at: null,
      },
    ]);

    render(<ClientAPIKeysPage />);

    // Wait for the key row to appear
    await screen.findByText("Test Key");

    // EmptyState should not be present
    expect(screen.queryByText("workspace.apiKeys.noKeysTitle")).not.toBeInTheDocument();
    expect(screen.getByText("Test Key")).toBeInTheDocument();
  });
});
