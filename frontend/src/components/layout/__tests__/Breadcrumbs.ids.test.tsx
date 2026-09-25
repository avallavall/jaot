/**
 * A breadcrumb shows an id as it is.
 *
 * Found driving the app (2026-09-25): the crumbs read "Exe_1848fe…" and
 * "Trg_e91c…". The fallback capitalised every segment without a translation,
 * and the ids in the path are the segments that have none.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/es/solve/executions/exe_1848fe0a2b",
}));

// Breadcrumbs reads the active workspace's name for workspace pages. No
// workspace is active on an execution page.
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: null, activeWorkspaceName: null }),
}));

import { Breadcrumbs, breadcrumbLabel } from "../Breadcrumbs";

describe("breadcrumb labels", () => {
  it("keeps an id exactly as it is in the path", () => {
    render(<Breadcrumbs />);

    expect(screen.getByText("exe_1848fe0a2b")).toBeInTheDocument();
    expect(screen.queryByText("Exe_1848fe0a2b")).toBeNull();
  });

  it("keeps trigger and uuid ids too, and still capitalises a plain word", () => {
    expect(breadcrumbLabel("trg_e91c77")).toBe("trg_e91c77");
    expect(breadcrumbLabel("3f2a9c1e-77aa-4c1b-9d7e-0b1f2c3d4e5f")).toBe(
      "3f2a9c1e-77aa-4c1b-9d7e-0b1f2c3d4e5f",
    );
    expect(breadcrumbLabel("overview")).toBe("Overview");
  });
});
