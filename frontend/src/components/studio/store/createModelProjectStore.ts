"use client";

import { createStore } from "zustand/vanilla";
import { temporal } from "zundo";
import type { OptimizationProblem, SolveResult } from "@/lib/types";
import type { ProgressPoint } from "@/lib/result-utils";
import type { SolveProgressEvent } from "../panels/solve/live-solve-metrics";
import { exceedsCanvasScale } from "./model-scale";

/** The lenses that can author the model. `scratch` = the JSON Editor, `dsl` = the JModel editor. */
export type RepKey = "canvas" | "scratch" | "formulation" | "dsl";
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
  /** The ModelExecution row id (`exe_…`), known from the enqueue response. Lets
   * the results drawer deep-link to the full execution-detail page. */
  executionId: string | null;
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
  executionId: null,
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
    startedAt?: string | null,
    executionId?: string | null
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

  /**
   * Which lenses currently hold un-parseable text (Editor JSON, JModel source).
   * A broken lens never applies its text to the canonical model, but records itself
   * here so solve/commit are blocked (`selectHasParseError`) — the user must not act
   * on a model they believe they just changed. One entry per authoring lens means a
   * broken JModel tab and a valid JSON editor never cross-block. The flag PERSISTS
   * when the lens unmounts (switching tab must not silently unblock a solve of the
   * last-good model); it clears when the text parses, when the model changes from
   * another source, or on reload.
   */
  parseErrors: Partial<Record<RepKey, boolean>>;
  setParseError: (rep: RepKey, hasError: boolean) => void;

  /** The JSON Editor's un-applied (un-parseable) text, retained here so it survives
   * the lens unmounting: coming back shows the broken text + its error instead of an
   * unexplained block. `null` = the editor is in sync with the canonical model and
   * derives its text from `problem`. Memory-only (never persisted to the draft);
   * cleared whenever the canonical model moves on (`setProblem`) or on reload. */
  scratchText: string | null;
  setScratchText: (scratchText: string | null) => void;

  /** The dataset ("scenario") the JModel lens compiles against — §8 model/data
   * separation. Lives in the store (not the lens) so the Solve tab can show which
   * data the canonical model was built with. `null` = inline `:=` values only.
   * In-memory per workspace: a reload falls back to null (the user re-picks). */
  activeDataset: { id: string; name: string } | null;
  setActiveDataset: (activeDataset: { id: string; name: string } | null) => void;

  /** The current JModel (DSL) source text for this project's HEAD draft. Persisted
   * to `draft_dsl_source` and rehydrated on load. It is the source of truth for the
   * JModel lens' textarea — the flat model is not projected back into DSL (one-way). */
  draftDslSource: string;
  /** True once the user has edited the JModel source this session. Gates persistence:
   * autosave sends `draft_dsl_source` (even empty, so a delete sticks) only when this
   * is set, which avoids a canvas-only save wiping a not-yet-hydrated source. */
  dslDirty: boolean;
  /** Set the JModel source. `dirty:true` marks the draft (and the DSL) dirty so autosave
   * persists it even when the text does not (yet) compile to a new model; the load-time
   * rehydrate uses the default (no dirty) so it never triggers a spurious save. */
  setDraftDslSource: (draftDslSource: string, opts?: { dirty?: boolean }) => void;
}

/** True when ANY authoring lens holds un-parseable text — blocks solve and commit. */
export function selectHasParseError(state: ModelProjectState): boolean {
  return Object.values(state.parseErrors).some(Boolean);
}

/** Cheap structural equality — the models are small plain JSON objects. */
export function problemsEqual(a: OptimizationProblem, b: OptimizationProblem): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

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
          // A change from source S makes every OTHER lens' text stale, so any parse
          // error they were holding no longer applies — the canonical model moved on.
          const parseErrors: Partial<Record<RepKey, boolean>> = {};
          for (const [rep, hasError] of Object.entries(get().parseErrors)) {
            if (rep === opts.source && hasError) parseErrors[rep as RepKey] = true;
          }
          set({
            problem: next,
            lastSource: opts.source,
            headDirty: true,
            parseErrors,
            // The canonical model moved on, so any retained un-applied editor text
            // no longer describes a pending fix — drop it with its parse error.
            scratchText: null,
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
            name,
            lastSource: null,
            headDirty: false,
            saveState: "idle",
            parseErrors: {},
            scratchText: null,
          });
        },

        setName: (name) => set({ name }),
        setSaveState: (saveState) => set({ saveState }),
        setLockVersion: (lockVersion) => set({ lockVersion }),
        markCommitted: () => set({ headDirty: false }),

        solveSession: IDLE_SOLVE_SESSION,
        startSolveSession: (taskId, solverName, startedAt = null, executionId = null) =>
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
              executionId,
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

        parseErrors: {},
        setParseError: (rep, hasError) =>
          set((state) => {
            const next = { ...state.parseErrors };
            if (hasError) next[rep] = true;
            else delete next[rep];
            return { parseErrors: next };
          }),

        scratchText: null,
        setScratchText: (scratchText) => set({ scratchText }),

        activeDataset: null,
        setActiveDataset: (activeDataset) => set({ activeDataset }),

        draftDslSource: "",
        dslDirty: false,
        setDraftDslSource: (draftDslSource, opts) =>
          set(
            opts?.dirty
              ? { draftDslSource, dslDirty: true, headDirty: true }
              : { draftDslSource }
          ),
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
