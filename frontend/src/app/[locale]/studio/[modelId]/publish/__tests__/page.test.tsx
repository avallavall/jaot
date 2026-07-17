import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import StudioPublishPage from "../page";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getProject: vi.fn(),
    getCatalogModel: vi.fn(),
    publishModel: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ modelId: "mp_pub_1" }),
}));

const intlRouterPush = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: intlRouterPush }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({
    showError: vi.fn(),
    showSuccess: vi.fn(),
    confirm: vi.fn().mockResolvedValue(true),
    DialogComponent: () => null,
  }),
}));

vi.mock("@/hooks/useCommonLabels", () => ({
  useCommonLabels: () => ({ categoryLabel: (id: string) => id }),
}));

// Heavy media/editor components are out of scope for this page test.
vi.mock("@/components/publish/RichTextEditor", () => ({
  RichTextEditor: () => <div data-testid="rich-text-editor" />,
}));
vi.mock("@/components/publish/LogoUpload", () => ({
  LogoUpload: ({ disabled }: { disabled?: boolean }) => (
    <div data-testid="logo-upload" data-disabled={disabled ? "true" : "false"} />
  ),
}));
vi.mock("@/components/publish/ScreenshotUpload", () => ({
  ScreenshotUpload: ({ disabled }: { disabled?: boolean }) => (
    <div data-testid="screenshot-upload" data-disabled={disabled ? "true" : "false"} />
  ),
}));

const mockApi = vi.mocked(api);

function project(overrides: Record<string, unknown> = {}) {
  return {
    id: "mp_pub_1",
    organization_id: "org_1",
    name: "My Model",
    // ≥ 10 chars — mirrors the backend's PublishModelRequest.description
    // min_length=10, which the form now also enforces client-side.
    description: "A demo optimization model",
    status: "active",
    committed_count: 1,
    current_version_id: "mpv_1",
    draft_lock_version: 0,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("StudioPublishPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("blocks publishing a never-committed project with a commit-first CTA", async () => {
    mockApi.getProject.mockResolvedValue(project({ committed_count: 0 }) as never);
    mockApi.getCatalogModel.mockRejectedValue(new Error("404"));

    render(<StudioPublishPage />);

    expect(await screen.findByText("solve.publish.commitFirstTitle")).toBeInTheDocument();
    screen.getByTestId("studio-publish-commit-first").click();
    expect(intlRouterPush).toHaveBeenCalledWith("/studio/mp_pub_1/build");
  });

  it("renders the publish form (media disabled) for a committed, unpublished project", async () => {
    mockApi.getProject.mockResolvedValue(project() as never);
    mockApi.getCatalogModel.mockRejectedValue(new Error("404"));

    render(<StudioPublishPage />);

    const form = await screen.findByTestId("studio-publish-form");
    expect(form).toBeInTheDocument();
    // First-publish copy on the submit button
    expect(screen.getByTestId("studio-publish-submit")).toHaveTextContent(
      "solve.publish.publishToMarketplace"
    );
    // Media operates on the listing → disabled before the first publish
    expect(screen.getByTestId("logo-upload")).toHaveAttribute("data-disabled", "true");
    expect(screen.getByTestId("screenshot-upload")).toHaveAttribute("data-disabled", "true");
    // The project name pre-fills the display name
    expect(screen.getByDisplayValue("My Model")).toBeInTheDocument();
  });

  it("switches to edit mode (update copy, media enabled) when a listing exists", async () => {
    mockApi.getProject.mockResolvedValue(project() as never);
    mockApi.getCatalogModel.mockResolvedValue({
      id: "mp_pub_1",
      display_name: "Published Name",
      description: "Published desc",
      short_description: "short",
      category: "finance",
      tags: ["a", "b"],
      logo_url: null,
      screenshot_urls: [],
    } as never);

    render(<StudioPublishPage />);

    await waitFor(() =>
      expect(screen.getByTestId("studio-publish-submit")).toHaveTextContent(
        "solve.publish.updateListing"
      )
    );
    expect(screen.getByDisplayValue("Published Name")).toBeInTheDocument();
    expect(screen.getByTestId("logo-upload")).toHaveAttribute("data-disabled", "false");
  });

  it("publishes and navigates to the marketplace listing (the id IS the project id)", async () => {
    mockApi.getProject.mockResolvedValue(project() as never);
    mockApi.getCatalogModel.mockRejectedValue(new Error("404"));
    mockApi.publishModel.mockResolvedValue({ id: "mp_pub_1" } as never);

    render(<StudioPublishPage />);
    const submit = await screen.findByTestId("studio-publish-submit");
    submit.click();

    await waitFor(() => expect(mockApi.publishModel).toHaveBeenCalled());
    expect(mockApi.publishModel).toHaveBeenCalledWith(
      "mp_pub_1",
      expect.objectContaining({ display_name: "My Model" })
    );
    await waitFor(() => expect(intlRouterPush).toHaveBeenCalledWith("/marketplace/mp_pub_1"));
  });
});
