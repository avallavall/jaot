import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * A 403 on the draft is not a transient failure and never becomes one.
 *
 * Somebody took this caller out of the model's workspace while the editor was
 * open. The load-time 403 was already handled — it renders the "no longer
 * yours" page — but the one that arrives LATER fell into the generic error
 * path: `saveState("error")` plus a retry every few seconds, forever. Driving
 * the app showed the consequence (QA, 2026-08-20): the editor stayed on screen,
 * the canvas still accepted typing, and nothing said a word until the page was
 * reloaded.
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

const updateDraft = api.updateProjectDraft as unknown as ReturnType<typeof vi.fn>;

interface FakeState {
  problem: unknown;
  draftDslSource: string;
  dslDirty: boolean;
  headDirty: boolean;
  lockVersion: number;
  saveState: string;
  archived: boolean;
  unsavedDraft: boolean;
  accessLost: boolean;
  setSaveState: (s: string) => void;
  setLockVersion: (v: number) => void;
  setUnsavedDraft: (v: boolean) => void;
  setAccessLost: (v: boolean) => void;
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
    archived: false,
    unsavedDraft: false,
    accessLost: false,
    setSaveState: (s) => {
      state = { ...state, saveState: s };
    },
    setLockVersion: (v) => {
      state = { ...state, lockVersion: v };
    },
    setUnsavedDraft: (v) => {
      state = { ...state, unsavedDraft: v };
    },
    setAccessLost: (v) => {
      state = { ...state, accessLost: v };
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
const RETRY_MS = 10_000;

function denied() {
  return Object.assign(new Error("You are not a member of this workspace"), { status: 403 });
}

async function editAndFlush(store: ReturnType<typeof makeStore>, problem: unknown) {
  await act(async () => {
    store.edit(problem);
    vi.advanceTimersByTime(DEBOUNCE_MS);
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("autosave when the workspace is taken away mid-session", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("raises accessLost so the editor can be replaced", async () => {
    const store = makeStore();
    updateDraft.mockRejectedValue(denied());
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useAutosave(store as any, "mp_1"));

    await editAndFlush(store, { variables: [{ name: "x" }] });

    expect(store.getState().accessLost).toBe(true);
    expect(store.getState().saveState).toBe("error");
  });

  it("stops retrying, because the answer can never change", async () => {
    const store = makeStore();
    updateDraft.mockRejectedValue(denied());
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useAutosave(store as any, "mp_1"));

    await editAndFlush(store, { variables: [{ name: "x" }] });
    expect(updateDraft).toHaveBeenCalledTimes(1);

    // Three retry windows. The old code sent one refused write per window and
    // would have kept going for as long as the tab stayed open.
    await act(async () => {
      vi.advanceTimersByTime(RETRY_MS * 3);
      await Promise.resolve();
    });

    expect(updateDraft).toHaveBeenCalledTimes(1);
  });

  it("still retries an ordinary failure, which may well succeed next time", async () => {
    const store = makeStore();
    updateDraft.mockRejectedValue(Object.assign(new Error("gateway"), { status: 502 }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useAutosave(store as any, "mp_1"));

    await editAndFlush(store, { variables: [{ name: "x" }] });
    expect(updateDraft).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(RETRY_MS);
      await Promise.resolve();
    });

    expect(updateDraft).toHaveBeenCalledTimes(2);
    expect(store.getState().accessLost).toBe(false);
  });
});
