"use client";

import { useEffect, useRef } from "react";
import { useStore } from "zustand";
import { api } from "@/lib/api";
import type { ModelProjectStore } from "./createModelProjectStore";

/**
 * Recompile the draft JModel source whenever the ACTIVE DATASET changes —
 * provider-level, like the solve/AI sessions, so "Use" applies everywhere.
 *
 * Without this, picking a dataset in the Datos tab only took effect after
 * visiting the JModel lens (the lens owns keystroke-driven compiles): going
 * straight to Solve left the canonical model empty/stale and the normal
 * Resolver greyed out while "Solve all" (which compiles per dataset itself)
 * worked — the owner's 2026-07-03 report.
 *
 * Guards:
 * - Skip on mount: the selection is a USER action; hydration owns load-time state.
 * - Skip when there is no DSL source (nothing to compile).
 * - Skip when the source is DRIFTED (`lastSource` ∉ {null, "dsl"}) or MAYBE-STALE
 *   (rehydrated by a reload/restore, sync unknowable): re-applying an unverified
 *   source over the canonical model is an EXPLICIT "recompile" in the JModel lens
 *   (8d5fabf), never a side effect of picking a dataset.
 * - Monotonic seq so a slow response can't overwrite a newer selection's result.
 */
export function useActiveDatasetCompile(store: ModelProjectStore): void {
  const activeDatasetId = useStore(store, (s) => s.activeDataset?.id ?? null);
  const seq = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    const { draftDslSource, lastSource, dslMaybeStale } = store.getState();
    if (!draftDslSource.trim()) return;
    if (dslMaybeStale) return;
    if (lastSource !== null && lastSource !== "dsl") return;
    const mySeq = ++seq.current;
    api
      .compileDsl(draftDslSource, activeDatasetId)
      .then((res) => {
        if (mySeq !== seq.current) return;
        const st = store.getState();
        if (res.ok && res.problem) {
          st.setParseError("dsl", false);
          st.setProblem(res.problem, { source: "dsl" });
        } else {
          // e.g. deselecting the dataset under a declaration-only source: the
          // model can no longer compile, so solve/commit must block again.
          st.setParseError("dsl", true);
        }
      })
      .catch(() => {
        /* transport/gate failure: leave the block state as-is (lens pattern) */
      });
  }, [activeDatasetId, store]);
}
