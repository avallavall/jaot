import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

/**
 * Restoring a version must not throw away work the user has not committed.
 *
 * The backend guards this: `checkout_into_draft` answers 409 when the draft is
 * dirty, and says in its own docstring that this is "so the caller can confirm".
 * This component used to pass `discard_draft=true` on every call, so the 409
 * could never happen — the question was answered for the user, always the same
 * way, and a toast then told them their work had been kept as a checkpoint when
 * nothing of the sort existed.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: undefined }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    listProjectVersions: vi.fn().mockResolvedValue([]),
    restoreProjectVersion: vi.fn(),
  },
}));

const storeState = {
  modelId: "mp_test",
  headDirty: true,
  parseErrors: {},
  hydrate: vi.fn(),
  setCanvasDisabled: vi.fn(),
  setDraftDslSource: vi.fn(),
  setLockVersion: vi.fn(),
  markCommitted: vi.fn(),
};

vi.mock("../../store/useModelProjectStore", () => ({
  useModelProjectStore: (selector: (s: typeof storeState) => unknown) => selector(storeState),
  useModelProjectStoreApi: () => ({ getState: () => storeState }),
}));

vi.mock("@/hooks/useBuilderStore", () => ({
  useBuilderStore: Object.assign(() => ({ nodes: [], edges: [] }), {
    getState: () => ({ nodes: [], edges: [], reset: vi.fn(), setDocument: vi.fn() }),
    setState: vi.fn(),
  }),
}));

vi.mock("../../store/draft-canvas", () => ({
  resolveDraftCanvas: () => ({ nodes: [], edges: [] }),
}));

vi.mock("@/lib/builder/serializer", () => ({
  serializeToOptimizationProblem: () => ({ variables: [], constraints: [] }),
}));

vi.mock("../../store/model-scale", () => ({
  canvasCanRepresentModel: () => true,
  exceedsCanvasScale: () => false,
}));

vi.mock("../CommitDialog", () => ({ CommitDialog: () => null }));
vi.mock("../VersionSelector", () => ({ VersionSelector: () => null }));

// A stand-in drawer whose button calls onRestore the way the real one does:
// with the version id and nothing else.
vi.mock("../VersionHistoryDrawer", () => ({
  VersionHistoryDrawer: ({ onRestore }: { onRestore: (id: string) => void }) => (
    <button data-testid="restore-v1" onClick={() => onRestore("ver_1")}>
      restore
    </button>
  ),
}));

import { VersionControls } from "../VersionControls";
import { api } from "@/lib/api";

const restore = api.restoreProjectVersion as unknown as ReturnType<typeof vi.fn>;

const RESTORED_PROJECT = {
  id: "mp_test",
  name: "Test",
  draft_model_json: null,
  draft_canvas_json: null,
  draft_dsl_source: "",
  draft_lock_version: 2,
};

function conflict() {
  return Object.assign(new Error("draft has uncommitted changes"), { status: 409 });
}

/**
 * Stand in for the real endpoint on a dirty draft: it answers 409 unless the
 * caller explicitly asks to discard. A mock that rejected regardless of the
 * argument would keep passing with `discard_draft` hardcoded back to true,
 * which is the exact defect these tests exist to catch.
 */
function backendWithDirtyDraft() {
  restore.mockImplementation((_id: string, _versionId: string, discardDraft: boolean) =>
    discardDraft ? Promise.resolve(RESTORED_PROJECT) : Promise.reject(conflict()),
  );
}

describe("restoring a version with uncommitted work", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // CONTRACT-TEST: restore never discards an uncommitted draft without asking
  it("asks the backend to keep the draft on the first attempt", async () => {
    backendWithDirtyDraft();
    render(<VersionControls />);

    screen.getByTestId("restore-v1").click();

    await waitFor(() => expect(restore).toHaveBeenCalled());
    const [, versionId, discardDraft] = restore.mock.calls[0];
    expect(versionId).toBe("ver_1");
    expect(discardDraft).toBe(false);
  });

  it("shows the discard confirmation instead of restoring, when the draft is dirty", async () => {
    backendWithDirtyDraft();
    render(<VersionControls />);

    screen.getByTestId("restore-v1").click();

    await waitFor(() =>
      expect(screen.getByTestId("studio-version-restore-discard-confirm")).toBeTruthy(),
    );
    expect(restore).toHaveBeenCalledTimes(1);
  });

  it("discards only after the user confirms", async () => {
    backendWithDirtyDraft();
    render(<VersionControls />);

    screen.getByTestId("restore-v1").click();
    const confirm = await screen.findByTestId("studio-version-restore-discard-confirm");
    confirm.click();

    await waitFor(() => expect(restore).toHaveBeenCalledTimes(2));
    expect(restore.mock.calls[1][2]).toBe(true);
  });
});
