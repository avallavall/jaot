"use client";

import { createStore } from "zustand/vanilla";
import { temporal } from "zundo";
import type { OptimizationProblem } from "@/lib/types";

/** The lenses that can author the model. Only `canvas` is live in P0/2A. */
export type RepKey = "canvas" | "scratch" | "formulation";
export type RepStatus = "synced" | "dirty" | "parse_error";
export type SaveState = "idle" | "saving" | "saved" | "error";

export interface ModelProjectState {
  /** Single source of truth — the solver-agnostic model. Only this is tracked by undo. */
  problem: OptimizationProblem;
  /** Last known-valid model; fallback when a representation has a parse error. */
  lastGoodProblem: OptimizationProblem;
  /** Sync status per representation (canvas / DSL editor / AI formulation). */
  repStatus: Record<RepKey, RepStatus>;
  /** Which representation produced the most recent `problem` change. */
  lastSource: RepKey | null;
  modelId: string;
  name: string;
  /** True when the draft has uncommitted edits since load / last save. */
  headDirty: boolean;
  saveState: SaveState;
  /** Optimistic-concurrency token for the ModelProject draft (the `If-Match` value). */
  lockVersion: number;

  /** Apply an edit from a representation; makes that rep canonical and the others stale. */
  setProblem: (next: OptimizationProblem, opts: { source: RepKey }) => void;
  /** Replace the model on load WITHOUT marking it dirty (no autosave, no undo pollution). */
  hydrate: (problem: OptimizationProblem, name: string) => void;
  /** Entering a tab clears that rep's dirty flag (reprojection lands with its slice). */
  enterTab: (rep: RepKey) => void;
  setName: (name: string) => void;
  setSaveState: (state: SaveState) => void;
  /** Update the draft lock version (from a load or a successful draft PUT). */
  setLockVersion: (lockVersion: number) => void;
  /** Mark the current draft as committed — clears the "uncommitted edits" flag. */
  markCommitted: () => void;
}

/** Cheap structural equality — the models are small plain JSON objects. */
export function problemsEqual(a: OptimizationProblem, b: OptimizationProblem): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

const OTHER_REPS: Record<RepKey, RepKey[]> = {
  canvas: ["scratch", "formulation"],
  scratch: ["canvas", "formulation"],
  formulation: ["canvas", "scratch"],
};

export interface ModelProjectInit {
  modelId: string;
  name: string;
  problem: OptimizationProblem;
}

export function createModelProjectStore(init: ModelProjectInit) {
  return createStore<ModelProjectState>()(
    temporal(
      (set, get) => ({
        problem: init.problem,
        lastGoodProblem: init.problem,
        repStatus: { canvas: "synced", scratch: "synced", formulation: "synced" },
        lastSource: null,
        modelId: init.modelId,
        name: init.name,
        headDirty: false,
        saveState: "idle",
        lockVersion: 0,

        setProblem: (next, opts) => {
          // Idempotency guard: a re-projection that yields the model already in hand
          // is a no-op. This is what stops the canvas <-> canonical bridge from looping
          // and prevents an autosave firing on load.
          if (problemsEqual(next, get().problem)) return;
          const repStatus: Record<RepKey, RepStatus> = {
            ...get().repStatus,
            [opts.source]: "synced",
          };
          for (const other of OTHER_REPS[opts.source]) repStatus[other] = "dirty";
          set({
            problem: next,
            lastGoodProblem: next,
            repStatus,
            lastSource: opts.source,
            headDirty: true,
          });
        },

        hydrate: (problem, name) => {
          set({
            problem,
            lastGoodProblem: problem,
            name,
            repStatus: { canvas: "synced", scratch: "synced", formulation: "synced" },
            lastSource: null,
            headDirty: false,
            saveState: "idle",
          });
        },

        enterTab: (rep) => {
          const { repStatus } = get();
          if (repStatus[rep] === "synced") return;
          set({ repStatus: { ...repStatus, [rep]: "synced" } });
        },

        setName: (name) => set({ name }),
        setSaveState: (saveState) => set({ saveState }),
        setLockVersion: (lockVersion) => set({ lockVersion }),
        markCommitted: () => set({ headDirty: false }),
      }),
      {
        // Undo tracks ONLY the canonical model, so "undo my last change" means the
        // same thing in every tab.
        partialize: (state) => ({ problem: state.problem }),
        limit: 100,
      }
    )
  );
}

export type ModelProjectStore = ReturnType<typeof createModelProjectStore>;
