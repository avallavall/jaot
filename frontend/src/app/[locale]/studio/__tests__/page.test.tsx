import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockListProjects, mockPush } = vi.hoisted(() => ({
  mockListProjects: vi.fn(),
  mockPush: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { listProjects: mockListProjects } }));
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: null }),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
  useRouter: () => ({ push: mockPush }),
}));

import StudioHomePage from "../page";

describe("StudioHomePage — My Models list", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the org's projects, each linking into its workspace", async () => {
    mockListProjects.mockResolvedValue([
      { id: "mp_1", name: "Crew Scheduler", status: "active", committed_count: 3, updated_at: "2026-06-29T10:00:00Z" },
      { id: "mp_2", name: "Diet", status: "active", committed_count: 0, updated_at: "2026-06-28T10:00:00Z" },
    ]);
    render(<StudioHomePage />);

    expect(await screen.findByText("Crew Scheduler")).toBeInTheDocument();
    expect(screen.getByText("Diet")).toBeInTheDocument();
    const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/studio/mp_1/build");
    expect(hrefs).toContain("/studio/mp_2/build");
  });

  it("shows the empty state only when the fetch returns zero projects", async () => {
    mockListProjects.mockResolvedValue([]);
    render(<StudioHomePage />);
    expect(await screen.findByText("studio.myModelsEmpty")).toBeInTheDocument();
  });

  it("shows an error state with retry when the fetch fails", async () => {
    mockListProjects.mockRejectedValue(new Error("nope"));
    render(<StudioHomePage />);
    expect(await screen.findByText("studio.myModelsError")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "studio.retry" })).toBeInTheDocument();
  });
});
