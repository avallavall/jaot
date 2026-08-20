"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { ModelProjectStore } from "./createModelProjectStore";

const DEBOUNCE_MS = 800;
// A failed save used to leave "Error al guardar" stuck until the NEXT edit (live
// 2026-07-04: an autosave that hit an api restart never healed). Retry on a slow
// cadence instead — the in-memory model is the truth and the save is idempotent.
const RETRY_MS = 10_000;

/**
 * Persists the canonical model to the `ModelProject` HEAD draft (`PUT
 * /projects/{id}/draft`) whenever it changes from a real edit. Idempotent no-ops
 * (e.g. the load-time projection) never set `headDirty`, so they do not trigger a
 * save.
 *
 * Optimistic concurrency via the `draft_lock_version`. A 409 says someone
 * advanced the draft, and WHO decides what to do:
 *
 * - **This client.** Two of our own saves overlapped and the newer one won
 *   (slow request A, fast request B). Retrying with the current in-memory model
 *   is right: the screen is the truth and no other person's work is at stake.
 * - **Somebody else.** Another tab, or another member of the organisation, is
 *   editing the same model. Retrying here overwrote their work while both
 *   screens still read "Saved" — reproduced with two tabs, where the second one
 *   silently won. We now stop, say so, and let the user choose to overwrite.
 *
 * The two are told apart by `ownVersions`: every lock version the server hands
 * back to THIS client is recorded, so a conflict against a version we never
 * produced came from someone else.
 */
export function useAutosave(store: ModelProjectStore, modelId: string): void {
  const { activeWorkspaceId } = useAuth();
  const t = useTranslations("studio");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Lock versions the server handed back to THIS client. A 409 against anything
  // else means another writer, not one of our own overlapping saves.
  const ownVersions = useRef<Set<number>>(new Set());
  // One warning per conflict, not one per retry.
  const conflictWarned = useRef(false);

  useEffect(() => {
    if (!modelId || modelId === "new") return;
    const ws = activeWorkspaceId ?? undefined;

    const buildBody = () => {
      const st = store.getState();
      const { nodes, edges } = useBuilderStore.getState();
      return {
        model_json: st.problem as unknown as Record<string, unknown>,
        canvas_json: { nodes, edges } as unknown as Record<string, unknown>,
        // Persist the JModel source once the user has touched it this session (`dslDirty`),
        // sending it even when empty so a deletion sticks. Before the user edits the DSL,
        // it is omitted so a canvas/JSON edit never wipes a not-yet-hydrated source.
        ...(st.dslDirty ? { dsl_source: st.draftDslSource } : {}),
      };
    };

    const accept = (lockVersion: number) => {
      ownVersions.current.add(lockVersion);
      store.getState().setLockVersion(lockVersion);
      store.getState().setSaveState("saved");
      // The server now has this edit, so leaving the page costs nothing.
      store.getState().setUnsavedDraft(false);
      conflictWarned.current = false;
    };

    /** Write over whatever is on the server, at the user's explicit request. */
    const overwrite = async () => {
      try {
        const latest = await api.getProject(modelId, ws);
        const forced = await api.updateProjectDraft(
          modelId,
          buildBody(),
          latest.draft_lock_version,
          ws
        );
        accept(forced.draft_lock_version);
      } catch {
        store.getState().setSaveState("error");
      }
    };

    const persist = () => {
      store.getState().setSaveState("saving");
      api
        .updateProjectDraft(modelId, buildBody(), store.getState().lockVersion, ws)
        .then((project) => accept(project.draft_lock_version))
        .catch(async (err: unknown) => {
          if ((err as { status?: number })?.status === 409) {
            try {
              const latest = await api.getProject(modelId, ws);
              if (ownVersions.current.has(latest.draft_lock_version)) {
                // Our own newer save won the race. Re-serialize from the CURRENT
                // store: retrying with the body from the losing attempt would
                // overwrite that newer save.
                const retry = await api.updateProjectDraft(
                  modelId,
                  buildBody(),
                  latest.draft_lock_version,
                  ws
                );
                accept(retry.draft_lock_version);
                return;
              }

              // Somebody else moved the draft. Do not touch it and do not keep
              // retrying: every retry here is an overwrite of their work.
              store.getState().setSaveState("error");
              if (!conflictWarned.current) {
                conflictWarned.current = true;
                toast.error(t("autosaveConflict"), {
                  duration: Infinity,
                  action: {
                    label: t("autosaveConflictOverwrite"),
                    onClick: () => void overwrite(),
                  },
                });
              }
              return;
            } catch {
              /* fall through to the error state below */
            }
          }
          // 403 is not a transient failure and never becomes one: somebody took
          // this caller out of the model's workspace while the editor was open.
          // Retrying it forever wrote a refused request every few seconds and
          // said nothing, so they kept typing into an editor that no longer
          // saved. The provider swaps in the "no longer yours" page on this.
          if ((err as { status?: number })?.status === 403) {
            store.getState().setSaveState("error");
            store.getState().setAccessLost(true);
            return;
          }
          store.getState().setSaveState("error");
          // Self-heal: retry with the latest in-memory state. A new edit replaces
          // this timer via the debounce path; unmount clears it.
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => persist(), RETRY_MS);
        });
    };

    const unsub = store.subscribe((state, prev) => {
      // An archived model refuses every write with a 409, and that 409 means
      // something else entirely here: the handler above would read it as another
      // writer having moved the draft and offer to overwrite their work, which
      // would 409 as well. Never start the save.
      if (state.archived) return;
      // Save on a real model change OR a JModel-source edit (which may not change the
      // compiled model — e.g. broken text — but must still be persisted so it survives
      // navigation). Load-time projections never set headDirty, so they don't save.
      if (state.problem === prev.problem && state.draftDslSource === prev.draftDslSource) return;
      if (!state.headDirty) return;
      // Raised here rather than in persist(): the debounce below is exactly the
      // window in which a reload took the edit with nothing said.
      store.getState().setUnsavedDraft(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => persist(), DEBOUNCE_MS);
    });

    return () => {
      if (timer.current) clearTimeout(timer.current);
      unsub();
    };
  }, [store, modelId, activeWorkspaceId, t]);
}
