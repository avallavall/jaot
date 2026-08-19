"use client";

import { useEffect } from "react";
import type { ModelProjectStore } from "./createModelProjectStore";

/**
 * Asks the browser to confirm before leaving with work that has not reached the
 * server yet.
 *
 * Autosave is an 800 ms debounce, and the JModel lens adds its own 500 ms
 * compile debounce on top, so the first second or so of typing exists only in
 * the tab. A reload in that window took it with no word said: the editor came
 * back empty and "Model at a glance" read 0 variables. Nothing else in the
 * workbench guarded against it.
 *
 * `beforeunload` covers reload, closing the tab and following a link out of the
 * app. It does NOT cover a route change inside the app, which the App Router
 * handles itself; those keep the store alive, so nothing is lost there.
 *
 * The text is the browser's own — every browser has ignored a custom message
 * for years. Setting `returnValue` is what asks for the dialog at all.
 */
export function useUnsavedGuard(store: ModelProjectStore): void {
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedWork(store.getState())) return;
      event.preventDefault();
      // Chrome still requires this, even though it shows its own wording.
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [store]);
}

/**
 * Whether this tab holds an edit the server does not have.
 *
 * Neither `saveState` nor the dirty flags answer this. `saveState` is still
 * "idle" through the debounce, which is the window this guard exists for;
 * `headDirty` means "different from the last commit" and stays true long after
 * a save; `dslDirty` means "the user has touched the source this session" and
 * is never cleared at all. `unsavedDraft` is the one that tracks the server:
 * autosave raises it when it schedules a write and drops it when one lands.
 */
export function hasUnsavedWork(state: { unsavedDraft: boolean; archived: boolean }): boolean {
  // An archived model refuses every write, so its edits can never be saved and
  // a warning would offer a choice that does not exist.
  return state.unsavedDraft && !state.archived;
}
