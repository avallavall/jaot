"use client";

import { createStore } from "zustand/vanilla";
import { temporal } from "zundo";
import type { OptimizationProblem, SolveResult } from "@/lib/types";
import type { ProgressPoint } from "@/lib/result-utils";
import type { SolveProgressEvent } from "../panels/solve/live-solve-metrics";
import { exceedsCanvasScale } from "./model-scale";

/** The lenses that can author the model. `scratch` = the JSON Editor, `dsl` = the JModel editor. */
export type RepKey = "canvas" | "scratch" | "formulation" | "dsl";
export type RepStatus = "synced" | "dirty" | "parse_error";
export type SaveState = "idle" | "saving" | "saved" | "error";

export type SolveStatus = "idle" | "running" | "done" | "failed" | "cancelled";

/**
 * The async-solve session. It lives in the canonical store (which is owned by the
 * workspace provider/layout) — NOT in `SolvePanel` — so it SURVIVES tab switches:
 * the panel unmounts when you move to Construir/Analizar, but the store and the
 * provider-level `useSolveSession` poller keep going, so coming back shows the
 * running/finished solve instead of a blank "start over".
 */
export interface SolveSession {
  taskId: string | null;
  status: SolveStatus;
  result: SolveResult | null;
  points: ProgressPoint[];
  lastEvent: SolveProgressEvent | null;
  solverName: string | null;
  error: string | null;
  /** ISO start time — `now` for a fresh solve, the server's start for a re-attach.
   * Powers the header's "solving… (started Xm ago)" ambient indicator. */
  startedAt: string | null;
}

export const IDLE_SOLVE_SESSION: SolveSession = {
  taskId: null,
  status: "idle",
  result: null,
  points: [],
  lastEvent: null,
  solverName: null,
  error: null,
  startedAt: null,
};

/** Terminal statuses a reconciled "last run" can carry (never running/pending). */
export type LastRunStatus = "completed" | "failed" | "cancelled" | "timeout";

/**
 * A compact summary of the most recent FINISHED solve, derived from the server
 * when the workspace opens. It lets the Solve panel say "última ejecución:
 * resuelta · objetivo X · hace Ys" instead of a blank box after the live session
 * was lost (reload / new tab / power loss). Shown only while no solve is active.
 */
export interface LastRunSummary {
  executionId: string;
  status: LastRunStatus;
  objectiveValue: number | null;
  solverName: string | null;
  finishedAt: string | null;
}

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

  /** The running/finished async solve (persists across tab switches). */
  solveSession: SolveSession;
  startSolveSession: (
    taskId: string,
    solverName: string | null,
    startedAt?: string | null
  ) => void;
  addSolvePoint: (point: ProgressPoint, event: SolveProgressEvent) => void;
  finishSolveSession: (result: SolveResult, points: ProgressPoint[]) => void;
  failSolveSession: (error: string) => void;
  cancelSolveSession: () => void;
  clearSolveSession: () => void;

  /** The most recent FINISHED solve, reconciled from the server on open. */
  lastRun: LastRunSummary | null;
  setLastRun: (lastRun: LastRunSummary | null) => void;

  /** True when the model is too large for the visual canvas (hairball guard):
   * the canvas lens is replaced by a notice and the canvas<->model bridge is
   * off. The model is still fully solvable from its canonical form. */
  canvasDisabled: boolean;
  setCanvasDisabled: (canvasDisabled: boolean) => void;

  /** True while the text Editor lens holds JSON that does not parse. The broken
   * text is never applied to the canonical model, but solve/commit are blocked
   * so the user does not act on a model they believe they just changed. Cleared
   * when the JSON parses, the model changes from another source, or on reload. */
  editorParseError: boolean;
  setEditorParseError: (editorParseError: boolean) => void;

  /** The current JModel (DSL) source text for this project's HEAD draft. Persisted
   * to `draft_dsl_source` and rehydrated on load. It is the source of truth for the
   * JModel lens' textarea — the flat model is not projected back into DSL (one-way). */
  draftDslSource: string;
  /** Set the JModel source. `dirty:true` marks the draft dirty so autosave persists
   * it even when the text does not (yet) compile to a new model; the load-time
   * rehydrate uses the default (no dirty) so it never triggers a spurious save. */
  setDraftDslSource: (draftDslSource: string, opts?: { dirty?: boolean }) => void;

  /** True while the JModel lens holds source that does not compile. Like
   * `editorParseError`, the broken source is never applied to the canonical model but
   * solve/commit are blocked. A separate flag so a broken JModel tab and a valid JSON
   * editor (or vice-versa) do not cross-block. */
  jmodelParseError: boolean;
  setJmodelParseError: (jmodelParseError: boolean) => void;
}

/** Cheap structural equality — the models are small plain JSON objects. */
export function problemsEqual(a: OptimizationProblem, b: OptimizationProblem): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

const OTHER_REPS: Record<RepKey, RepKey[]> = {
  canvas: ["scratch", "formulation", "dsl"],
  scratch: ["canvas", "formulation", "dsl"],
  formulation: ["canvas", "scratch", "dsl"],
  dsl: ["canvas", "scratch", "formulation"],
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
        repStatus: { canvas: "synced", scratch: "synced", formulation: "synced", dsl: "synced" },
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
            // A change from the canvas/restore makes any pending Editor parse error
            // stale — the canonical model just moved on, so clear the block.
            ...(opts.source !== "scratch" ? { editorParseError: false } : {}),
            // Symmetric to the Editor: a change from any lens other than the JModel
            // editor moots a stale JModel compile error.
            ...(opts.source !== "dsl" ? { jmodelParseError: false } : {}),
            // Re-evaluate the canvas hairball guard whenever a NON-canvas source
            // (AI Assistant / Editor) replaces the model. Without this the flag is
            // sticky: a model loaded large (canvas disabled) that the Assistant then
            // replaces with a SMALL one would keep the canvas disabled, leaving an
            // empty/degenerate canvas saved next to the new model_json (the source of
            // the "model shows 0 / empty after reload" data divergence). Recomputing
            // re-enables the canvas for a large→small swap (so it lays out and
            // autosave persists a canvas that matches the model) and disables it for
            // a small→large swap. The canvas source never needs this — if it is
            // authoring, the canvas is by definition already enabled.
            ...(opts.source !== "canvas" ? { canvasDisabled: exceedsCanvasScale(next) } : {}),
          });
        },

        hydrate: (problem, name) => {
          set({
            problem,
            lastGoodProblem: problem,
            name,
            repStatus: { canvas: "synced", scratch: "synced", formulation: "synced", dsl: "synced" },
            lastSource: null,
            headDirty: false,
            saveState: "idle",
            editorParseError: false,
            jmodelParseError: false,
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

        solveSession: IDLE_SOLVE_SESSION,
        startSolveSession: (taskId, solverName, startedAt = null) =>
          set({
            solveSession: {
              taskId,
              status: "running",
              result: null,
              points: [],
              lastEvent: null,
              solverName,
              error: null,
              startedAt,
            },
          }),
        addSolvePoint: (point, event) => {
          const s = get().solveSession;
          if (s.status !== "running") return;
          set({ solveSession: { ...s, points: [...s.points, point], lastEvent: event } });
        },
        finishSolveSession: (result, points) =>
          set((state) => ({
            solveSession: { ...state.solveSession, status: "done", result, points },
          })),
        failSolveSession: (error) =>
          set((state) => ({ solveSession: { ...state.solveSession, status: "failed", error } })),
        cancelSolveSession: () =>
          set((state) => ({ solveSession: { ...state.solveSession, status: "cancelled" } })),
        clearSolveSession: () => set({ solveSession: IDLE_SOLVE_SESSION }),

        lastRun: null,
        setLastRun: (lastRun) => set({ lastRun }),

        canvasDisabled: false,
        setCanvasDisabled: (canvasDisabled) => set({ canvasDisabled }),

        editorParseError: false,
        setEditorParseError: (editorParseError) => set({ editorParseError }),

        draftDslSource: "",
        setDraftDslSource: (draftDslSource, opts) =>
          set(opts?.dirty ? { draftDslSource, headDirty: true } : { draftDslSource }),

        jmodelParseError: false,
        setJmodelParseError: (jmodelParseError) => set({ jmodelParseError }),
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
