import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

/**
 * Autosave is an 800 ms debounce, and the JModel lens adds a 500 ms compile
 * debounce on top. A reload inside that window took the edit with nothing said:
 * the editor came back empty and "Model at a glance" read 0 variables. Nothing
 * in the workbench guarded against it.
 */

import { createModelProjectStore } from "../createModelProjectStore";
import { hasUnsavedWork, useUnsavedGuard } from "../useUnsavedGuard";

const PROBLEM = {
  variables: [{ name: "x", type: "continuous" as const, lower_bound: 0 }],
  objective: { sense: "maximize" as const, expression: "x" },
  constraints: [],
};

function makeStore() {
  return createModelProjectStore({ modelId: "mp_1", name: "Test", problem: PROBLEM });
}

describe("hasUnsavedWork", () => {
  it("is true while an edit has not reached the server", () => {
    expect(hasUnsavedWork({ unsavedDraft: true, archived: false })).toBe(true);
  });

  it("is false once a save has landed", () => {
    expect(hasUnsavedWork({ unsavedDraft: false, archived: false })).toBe(false);
  });

  // An archived model refuses every write, so a warning would offer a choice
  // that does not exist.
  it("is false for an archived model, which can never be saved", () => {
    expect(hasUnsavedWork({ unsavedDraft: true, archived: true })).toBe(false);
  });
});

describe("useUnsavedGuard", () => {
  let listeners: Array<(event: BeforeUnloadEvent) => void>;
  let addSpy: ReturnType<typeof vi.spyOn>;
  let removeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    listeners = [];
    addSpy = vi
      .spyOn(window, "addEventListener")
      .mockImplementation((type: string, handler: unknown) => {
        if (type === "beforeunload") {
          listeners.push(handler as (event: BeforeUnloadEvent) => void);
        }
      });
    removeSpy = vi.spyOn(window, "removeEventListener").mockImplementation(() => {});
  });

  afterEach(() => {
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  function fire() {
    const event = { preventDefault: vi.fn(), returnValue: undefined } as unknown as
      BeforeUnloadEvent & { preventDefault: ReturnType<typeof vi.fn> };
    listeners.forEach((handler) => handler(event));
    return event;
  }

  // CONTRACT-TEST: leaving with an edit the server does not have asks first
  it("asks the browser to confirm when a draft is waiting to be saved", () => {
    const store = makeStore();
    renderHook(() => useUnsavedGuard(store));

    act(() => store.getState().setUnsavedDraft(true));

    expect(fire().preventDefault).toHaveBeenCalled();
  });

  it("says nothing when the server already has everything", () => {
    const store = makeStore();
    renderHook(() => useUnsavedGuard(store));

    expect(fire().preventDefault).not.toHaveBeenCalled();
  });

  it("says nothing again once the save lands", () => {
    const store = makeStore();
    renderHook(() => useUnsavedGuard(store));

    act(() => store.getState().setUnsavedDraft(true));
    act(() => store.getState().setUnsavedDraft(false));

    expect(fire().preventDefault).not.toHaveBeenCalled();
  });

  it("lets go of the listener when the workbench unmounts", () => {
    const store = makeStore();
    const { unmount } = renderHook(() => useUnsavedGuard(store));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("beforeunload", expect.any(Function));
  });
});
