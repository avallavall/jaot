"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Save indicator state machine.
// States: idle | unsaved | saving | saved | error.
// Transitions: any change → unsaved; save start → saving; success → saved → idle (after delay);
// failure → error. Canvas edits from saved/error roll back to unsaved.

export type SaveState = "idle" | "unsaved" | "saving" | "saved" | "error";

/** How long "Saved" text stays visible before reverting to idle */
const SAVED_DISPLAY_MS = 4_000;

interface SaveIndicatorState {
  /** Current save state */
  state: SaveState;
  /** Timestamp (ms) of last successful save, or null if never saved */
  lastSavedAt: number | null;
}

interface SaveIndicatorActions {
  /** Call when the user's canvas changes (nodes, edges, name) */
  markUnsaved: () => void;
  /** Call when a save request starts */
  markSaving: () => void;
  /** Call when a save request succeeds */
  markSaved: () => void;
  /** Call when a save request fails */
  markError: () => void;
}

export type UseSaveIndicatorReturn = SaveIndicatorState & SaveIndicatorActions;

export function useSaveIndicator(): UseSaveIndicatorReturn {
  const [state, setState] = useState<SaveState>("idle");
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (savedTimerRef.current) {
        clearTimeout(savedTimerRef.current);
      }
    };
  }, []);

  const markUnsaved = useCallback(() => {
    if (savedTimerRef.current) {
      clearTimeout(savedTimerRef.current);
      savedTimerRef.current = null;
    }
    setState("unsaved");
  }, []);

  const markSaving = useCallback(() => {
    if (savedTimerRef.current) {
      clearTimeout(savedTimerRef.current);
      savedTimerRef.current = null;
    }
    setState("saving");
  }, []);

  const markSaved = useCallback(() => {
    const now = Date.now();
    setLastSavedAt(now);
    setState("saved");

    // Auto-transition to idle unless markUnsaved fires first.
    if (savedTimerRef.current) {
      clearTimeout(savedTimerRef.current);
    }
    savedTimerRef.current = setTimeout(() => {
      setState((current) => (current === "saved" ? "idle" : current));
      savedTimerRef.current = null;
    }, SAVED_DISPLAY_MS);
  }, []);

  const markError = useCallback(() => {
    if (savedTimerRef.current) {
      clearTimeout(savedTimerRef.current);
      savedTimerRef.current = null;
    }
    setState("error");
  }, []);

  return {
    state,
    lastSavedAt,
    markUnsaved,
    markSaving,
    markSaved,
    markError,
  };
}
