import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * A 409 on the draft means somebody advanced it. Who that somebody is decides
 * everything.
 *
 * Two of this client's own saves overlapping is a race worth retrying: the
 * screen is the truth and nobody else loses anything. Another tab or another
 * person editing the same model is not — the old code refetched the lock and
 * retried regardless, so the second writer always won, the first one's work was
 * gone, and both screens still read "Saved".
 */

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: undefined }),
}));

vi.mock("@/hooks/useBuilderStore", () => ({
  useBuilderStore: Object.assign(() => ({ nodes: [], edges: [] }), {
    getState: () => ({ nodes: [], edges: [] }),
  }),
}));

vi.mock("@/lib/api", () => ({
  api: { updateProjectDraft: vi.fn(), getProject: vi.fn() },
}));

import { useAutosave } from "../useAutosave";
import { api } from "@/lib/api";
import { toast } from "sonner";

const updateDraft = api.updateProjectDraft as unknown as ReturnType<typeof vi.fn>;
const getProject = api.getProject as unknown as ReturnType<typeof vi.fn>;

interface FakeState {
  problem: unknown;
  draftDslSource: string;
  dslDirty: boolean;
  headDirty: boolean;
  lockVersion: number;
  saveState: string;
  setSaveState: (s: string) => void;
  setLockVersion: (v: number) => void;
}

/** The slice of the model-project store the hook actually touches. */
function makeStore() {
  const listeners = new Set<(s: FakeState, p: FakeState) => void>();
  let state: FakeState = {
    problem: { variables: [] },
    draftDslSource: "",
    dslDirty: false,
    headDirty: false,
    lockVersion: 1,
    saveState: "idle",
    setSaveState: (s) => {
      state = { ...state, saveState: s };
    },
    setLockVersion: (v) => {
      state = { ...state, lockVersion: v };
    },
  };
  return {
    getState: () => state,
    subscribe: (listener: (s: FakeState, p: FakeState) => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    edit: (problem: unknown) => {
      const prev = state;
      state = { ...state, problem, headDirty: true };
      listeners.forEach((l) => l(state, prev));
    },
  };
}

const DEBOUNCE_MS = 800;

function conflict() {
  return Object.assign(new Error("stale lock"), { status: 409 });
}

async function editAndFlush(store: ReturnType<typeof makeStore>, problem: unknown) {
  await act(async () => {
    store.edit(problem);
    vi.advanceTimersByTime(DEBOUNCE_MS);
  });
  // Let the promise chain inside persist() settle.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("autosave on a conflicting draft", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries when the conflict came from this client's own overlapping save", async () => {
    const store = makeStore();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useAutosave(store as any, "mp_1"));

    updateDraft.mockResolvedValueOnce({ draft_lock_version: 5 });
    await editAndFlush(store, { variables: ["a"] });
    expect(store.getState().saveState).toBe("saved");

    // Version 5 is ours, so a 409 against it is our own race.
    updateDraft.mockRejectedValueOnce(conflict());
    getProject.mockResolvedValueOnce({ draft_lock_version: 5 });
    updateDraft.mockResolvedValueOnce({ draft_lock_version: 6 });

    await editAndFlush(store, { variables: ["a", "b"] });

    expect(store.getState().saveState).toBe("saved");
    expect(store.getState().lockVersion).toBe(6);
    expect(toast.error).not.toHaveBeenCalled();
  });

  // CONTRACT-TEST: another writer's draft is never overwritten without asking
  it("stops and warns when somebody else advanced the draft", async () => {
    const store = makeStore();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useAutosave(store as any, "mp_1"));

    updateDraft.mockResolvedValueOnce({ draft_lock_version: 5 });
    await editAndFlush(store, { variables: ["a"] });

    // Version 9 was never handed to us: another tab or another person wrote it.
    updateDraft.mockRejectedValueOnce(conflict());
    getProject.mockResolvedValueOnce({ draft_lock_version: 9 });

    await editAndFlush(store, { variables: ["a", "b"] });

    // One PUT for the first save, one for the attempt that lost. No third.
    expect(updateDraft).toHaveBeenCalledTimes(2);
    expect(store.getState().saveState).toBe("error");
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("warns once, not on every retry", async () => {
    const store = makeStore();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useAutosave(store as any, "mp_1"));

    updateDraft.mockResolvedValueOnce({ draft_lock_version: 5 });
    await editAndFlush(store, { variables: ["a"] });

    for (const version of [9, 10]) {
      updateDraft.mockRejectedValueOnce(conflict());
      getProject.mockResolvedValueOnce({ draft_lock_version: version });
      await editAndFlush(store, { variables: ["a", String(version)] });
    }

    expect(toast.error).toHaveBeenCalledTimes(1);
  });
});
