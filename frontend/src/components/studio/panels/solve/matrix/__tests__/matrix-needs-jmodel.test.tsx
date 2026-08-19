import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

/**
 * The Solve tab spent the first seconds of every load telling the reader their
 * model has no JModel formulation, with a link inviting them to go and write
 * one, and then took it back.
 *
 * Nothing was wrong with the model. `draftDslSource` starts empty in the store
 * and is filled by the project GET, so the panel was reading "not loaded yet"
 * as "this model has none". Anything that reads an empty store field as a fact
 * about the model now waits for `projectLoaded`.
 */

const { getProject } = vi.hoisted(() => ({ getProject: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    getProject,
    solverComparison: {
      batches: {
        list: vi.fn().mockResolvedValue([]),
        create: vi.fn(),
        cancel: vi.fn(),
        get: vi.fn(),
      },
      get: vi.fn(),
    },
  },
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: undefined }),
}));

vi.mock("@/hooks/useBuilderStore", () => ({
  useBuilderStore: Object.assign(() => ({ nodes: [], edges: [] }), {
    getState: () => ({ nodes: [], edges: [], reset: vi.fn(), setDocument: vi.fn() }),
    setState: vi.fn(),
  }),
}));

vi.mock("../../../../store/useCanvasBridge", () => ({ useCanvasBridge: () => {} }));
vi.mock("../../../../store/useAutosave", () => ({ useAutosave: () => {} }));
vi.mock("../../../../store/useSolveSession", () => ({ useSolveSession: () => {} }));
vi.mock("../../../../store/useActiveDatasetCompile", () => ({
  useActiveDatasetCompile: () => {},
}));
vi.mock("../../../../assistant/StudioAssistantProvider", () => ({
  StudioAssistantProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../../../explain/ModelExplanationProvider", () => ({
  ModelExplanationProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// The matrix needs at least one dataset to render at all, and a solver list to
// tick. Neither decides what this test asserts.
vi.mock("../../../../datasets/useProjectDatasets", () => ({
  useProjectDatasets: () => ({
    datasets: [{ id: "ds_1", name: "January", row_count: 10 }],
    loading: false,
    refresh: vi.fn(),
  }),
}));
vi.mock("@/hooks/useSolvers", () => ({
  useSolvers: () => ({ availableSolvers: [], solversLoading: false }),
  isComparable: () => true,
}));

import { ModelProjectStoreProvider } from "../../../../store/ModelProjectStoreProvider";
import { SolverMatrixSection } from "../SolverMatrixSection";

const NEEDS_JMODEL = "studio-matrix-needs-jmodel";

function project(overrides: Record<string, unknown> = {}) {
  return {
    id: "mp_1",
    name: "Test",
    status: "active",
    draft_model_json: null,
    draft_canvas_json: null,
    draft_dsl_source: "set P := {1,2};",
    draft_lock_version: 3,
    ...overrides,
  };
}

describe("the matrix's 'this model has no JModel source' panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // CONTRACT-TEST: an empty store field is not a fact about the model
  it("says nothing about the source until the project has been read", async () => {
    let resolveGet: (value: unknown) => void = () => {};
    getProject.mockReturnValue(
      new Promise((resolve) => {
        resolveGet = resolve;
      })
    );

    render(
      <ModelProjectStoreProvider modelId="mp_1">
        <SolverMatrixSection />
      </ModelProjectStoreProvider>
    );

    // The GET has not answered. The store's source is empty because nothing has
    // filled it in, which is not the same as the model having none.
    expect(screen.queryByTestId(NEEDS_JMODEL)).not.toBeInTheDocument();

    resolveGet(project());
    await waitFor(() =>
      expect(screen.getByTestId("studio-matrix")).toBeInTheDocument()
    );
    expect(screen.queryByTestId(NEEDS_JMODEL)).not.toBeInTheDocument();
  });

  it("says so once the project is read and really has no source", async () => {
    getProject.mockResolvedValue(project({ draft_dsl_source: "" }));

    render(
      <ModelProjectStoreProvider modelId="mp_1">
        <SolverMatrixSection />
      </ModelProjectStoreProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId(NEEDS_JMODEL)).toBeInTheDocument()
    );
  });
});
