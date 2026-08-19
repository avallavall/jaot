import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

/**
 * A link to a model somebody deleted used to land on the model list with
 * nothing said. On the Solve tab it was worse: `/solve/<id>/history` redirects
 * into the workspace, and the workbench opened in full — tabs, solver picker
 * and an enabled Solve button — over a model the server answers 404 for.
 */

const { getProject, push } = vi.hoisted(() => ({ getProject: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { getProject } }));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push }),
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: undefined }),
}));

vi.mock("@/hooks/useBuilderStore", () => ({
  useBuilderStore: Object.assign(() => ({ nodes: [], edges: [] }), {
    getState: () => ({ nodes: [], edges: [], reset: vi.fn() }),
    setState: vi.fn(),
  }),
}));

// The workspace hooks talk to the network and the canvas; none of them decides
// what this test asserts.
vi.mock("../useCanvasBridge", () => ({ useCanvasBridge: () => {} }));
vi.mock("../useAutosave", () => ({ useAutosave: () => {} }));
vi.mock("../useSolveSession", () => ({ useSolveSession: () => {} }));
vi.mock("../useActiveDatasetCompile", () => ({ useActiveDatasetCompile: () => {} }));
vi.mock("../../assistant/StudioAssistantProvider", () => ({
  StudioAssistantProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../explain/ModelExplanationProvider", () => ({
  ModelExplanationProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import { ModelProjectStoreProvider } from "../ModelProjectStoreProvider";
import { toast } from "sonner";

const WORKSPACE = <div>the whole workbench</div>;

describe("a model the server answers 404 for", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says it no longer exists instead of opening the workbench", async () => {
    getProject.mockRejectedValue({ status: 404 });

    render(<ModelProjectStoreProvider modelId="mp_gone">{WORKSPACE}</ModelProjectStoreProvider>);

    await waitFor(() =>
      expect(screen.getByText("studio.missing.title")).toBeInTheDocument(),
    );
    expect(screen.queryByText("the whole workbench")).not.toBeInTheDocument();
    // No silent bounce to the model list: the page says what happened.
    expect(push).not.toHaveBeenCalled();
  });

  it("offers the way back and the runs the model left behind", async () => {
    getProject.mockRejectedValue({ status: 404 });

    render(<ModelProjectStoreProvider modelId="mp_gone">{WORKSPACE}</ModelProjectStoreProvider>);

    const back = await screen.findByText("studio.missing.backToModels");
    expect(back.closest("a")).toHaveAttribute("href", "/studio");
    expect(screen.getByText("studio.missing.seeRuns").closest("a")).toHaveAttribute(
      "href",
      "/solve/executions",
    );
  });

  it("still bounces on a failure that is not a 404", async () => {
    getProject.mockRejectedValue({ status: 500 });

    render(<ModelProjectStoreProvider modelId="mp_boom">{WORKSPACE}</ModelProjectStoreProvider>);

    await waitFor(() => expect(push).toHaveBeenCalledWith("/studio"));
    expect(toast.error).toHaveBeenCalledWith("studio.loadFailed");
    expect(screen.queryByText("studio.missing.title")).not.toBeInTheDocument();
  });
});
