/**
 * A workspace page's breadcrumb names the workspace.
 *
 * The segment is the workspace id, and it was printed capitalized
 * ("Wks_3273a900…") in every locale (QA, 2026-09-25).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/es/workspace/workspaces/wks_3273a900be26cfb9",
}));

const auth = {
  activeWorkspaceId: "wks_3273a900be26cfb9" as string | null,
  activeWorkspaceName: "QA Shared Workspace" as string | null,
};
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

import { Breadcrumbs } from "../Breadcrumbs";

describe("Breadcrumbs on a workspace page", () => {
  it("shows the workspace name, not its id", () => {
    render(<Breadcrumbs />);

    const current = screen.getByText("QA Shared Workspace");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText(/Wks_/)).toBeNull();
  });

  it("keeps the other segments translated", () => {
    render(<Breadcrumbs />);

    expect(screen.getByText("common.breadcrumbs.workspace")).toBeInTheDocument();
    expect(screen.getByText("common.breadcrumbs.workspaces")).toBeInTheDocument();
  });
});
