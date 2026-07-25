"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "jaot_llm_advanced_model";

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Another tab flipping the choice counts too.
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function getSnapshot(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    // Storage denied (private mode / blocked cookies) — the default stands.
    return false;
  }
}

/** The server has no localStorage; render the default and let hydration correct it. */
function getServerSnapshot(): boolean {
  return false;
}

/**
 * Whether the assistant should answer with the advanced model.
 *
 * Backed by a real external store rather than component state so every panel
 * sees the same value AT ONCE: the studio chat sends through its provider while
 * the toggle lives in the lens, and two independent copies of this preference
 * would drift the moment the user flipped one of them.
 *
 * Defaults to false — the advanced tier costs several times more per call, so it
 * is always something the user asks for, never something they inherit.
 */
export function useAdvancedModel(): [boolean, (value: boolean) => void] {
  const advanced = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const update = useCallback((value: boolean) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(value));
    } catch {
      // Non-fatal: the choice simply does not survive this session.
    }
    // `storage` does not fire in the tab that wrote it — notify our own listeners.
    for (const listener of listeners) listener();
  }, []);

  return [advanced, update];
}
