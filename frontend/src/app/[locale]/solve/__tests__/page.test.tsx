import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import type { ModelCategory, OrganizationModel } from "@/lib/types";

// Mock api
vi.mock("@/lib/api", () => ({
  api: {
    getMyModels: vi.fn(),
    updateMyModel: vi.fn(),
    deactivateMyModel: vi.fn(),
  },
  OrganizationModel: {},
}));

// Mock dialog
vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({
    confirmCallback: vi.fn((msg: string, cb: () => void) => cb()),
    showSuccess: vi.fn(),
    showError: vi.fn(),
    DialogComponent: () => null,
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/solve",
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
  usePathname: () => "/solve",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  redirect: vi.fn(),
  getPathname: vi.fn(),
}));

import MyModelsPage from "../page";
import { api } from "@/lib/api";

const makeModel = (overrides: Partial<OrganizationModel> = {}): OrganizationModel => ({
  id: "m1",
  organization_id: "o1",
  catalog_id: "c1",
  display_name: "Test Model",
  description: "A test optimization model",
  category: "routing" as ModelCategory,
  is_active: true,
  is_favorite: false,
  total_executions: 5,
  total_credits_used: 50,
  credits_per_execution: 10,
  created_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

describe("MyModelsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading spinner initially", () => {
    vi.mocked(api.getMyModels).mockReturnValue(new Promise(() => {}));
    render(<MyModelsPage />);
    expect(document.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("renders model cards after loading", async () => {
    vi.mocked(api.getMyModels).mockResolvedValue({
      items: [makeModel()],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
    });

    render(<MyModelsPage />);

    await waitFor(() => {
      expect(screen.getByText("Test Model")).toBeInTheDocument();
    });
  });

  it("shows empty state when no models", async () => {
    vi.mocked(api.getMyModels).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 0,
    });

    render(<MyModelsPage />);

    await waitFor(() => {
      expect(screen.getByText("solve.list.noModels")).toBeInTheDocument();
    });
  });

  it("separates favorites from regular models", async () => {
    vi.mocked(api.getMyModels).mockResolvedValue({
      items: [
        makeModel({ id: "m1", display_name: "Fav Model", is_favorite: true }),
        makeModel({ id: "m2", display_name: "Regular Model", is_favorite: false }),
      ],
      total: 2,
      page: 1,
      page_size: 20,
      total_pages: 1,
    });

    render(<MyModelsPage />);

    await waitFor(() => {
      expect(screen.getByText("solve.list.favorites")).toBeInTheDocument();
      expect(screen.getByText("Fav Model")).toBeInTheDocument();
      expect(screen.getByText("Regular Model")).toBeInTheDocument();
    });
  });

  it("calls api.updateMyModel when toggling favorite", async () => {
    vi.mocked(api.getMyModels).mockResolvedValue({
      items: [makeModel()],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
    });
    vi.mocked(api.updateMyModel).mockResolvedValue({} as unknown as OrganizationModel);

    render(<MyModelsPage />);

    await waitFor(() => expect(screen.getByText("Test Model")).toBeInTheDocument());

    const starButton = document.querySelector("button .lucide-star")?.closest("button");
    if (starButton) await userEvent.click(starButton);

    await waitFor(() => {
      expect(api.updateMyModel).toHaveBeenCalledWith("m1", { is_favorite: true });
    });
  });

  it("reloads models when search input changes", async () => {
    vi.mocked(api.getMyModels).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 0,
    });

    render(<MyModelsPage />);

    await waitFor(() => expect(api.getMyModels).toHaveBeenCalledTimes(1));

    const searchInput = screen.getByPlaceholderText(/solve\.list\.searchPlaceholder/i);
    await userEvent.type(searchInput, "logistics");

    // Debounced - wait for debounce delay + api call
    await waitFor(
      () => expect(api.getMyModels).toHaveBeenCalledTimes(2),
      { timeout: 1000 }
    );

    expect(vi.mocked(api.getMyModels).mock.calls[1][0]).toMatchObject({
      search: "logistics",
    });
  });
});
