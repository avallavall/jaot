"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import type { OptimizationProblem } from "@/lib/types";
import { resolveDraftCanvas } from "./draft-canvas";
import {
  createModelProjectStore,
  type ModelProjectStore,
} from "./createModelProjectStore";
import { ModelProjectStoreContext } from "./useModelProjectStore";
import { canvasCanRepresentModel, exceedsCanvasScale } from "./model-scale";
import { useCanvasBridge } from "./useCanvasBridge";
import { useAutosave } from "./useAutosave";
import { useUnsavedGuard } from "./useUnsavedGuard";
import { useSolveSession } from "./useSolveSession";
import { useActiveDatasetCompile } from "./useActiveDatasetCompile";
import { StudioAssistantProvider } from "../assistant/StudioAssistantProvider";
import { ModelExplanationProvider } from "../explain/ModelExplanationProvider";
import { MissingModel } from "../MissingModel";

const EMPTY_PROBLEM: OptimizationProblem = {
  variables: [],
  objective: { sense: "minimize", expression: "0" },
  constraints: [],
};

interface ModelProjectStoreProviderProps {
  modelId: string;
  children: React.ReactNode;
}

/**
 * Owns the canonical model store for one model and loads it once. Mount it with a
 * `key={modelId}` so navigating between models yields a fresh store. The canonical
 * model is hydrated from `serialize(canvas)` (never the cached `model_json`) so the
 * canvas bridge's first pass is an idempotent no-op — no spurious autosave on load.
 */
export function ModelProjectStoreProvider({
  modelId,
  children,
}: ModelProjectStoreProviderProps) {
  const t = useTranslations("studio");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();

  // Set when the server answers 404 for this model: it was deleted, or the id
  // never existed. The workspace is not rendered at all in that case.
  const [missing, setMissing] = useState(false);

  // Lazy one-time init (the provider is keyed by modelId, so a fresh model gets a
  // fresh store). useState — not useRef — so the store is not read during render.
  const [store] = useState<ModelProjectStore>(() =>
    createModelProjectStore({
      modelId,
      name: "Untitled Model",
      problem: EMPTY_PROBLEM,
    })
  );

  // `router`/`t` are used only in the load effect's error branch. Keep them in refs
  // (not effect deps) so a client-side tab navigation (Build→Solve), which can hand
  // back new `router`/`t` refs, does NOT re-run the load. Re-running it would
  // re-hydrate from the server draft and silently discard in-memory edits autosave
  // has not yet persisted (e.g. a just-compiled JModel), emptying the model on a tab
  // switch. The load re-runs only on a real model/workspace change (its true deps).
  const routerRef = useRef(router);
  const tRef = useRef(t);
  // True once the first project load has been handled (applied or yielded to
  // in-flight user edits) — later runs (workspace switch) always re-hydrate.
  const firstLoadDone = useRef(false);
  useEffect(() => {
    routerRef.current = router;
    tRef.current = t;
  });

  useEffect(() => {
    let cancelled = false;
    const builder = useBuilderStore.getState();

    if (!modelId || modelId === "new") {
      // Seeded by a launcher flow (or empty): derive canonical from current canvas.
      const seeded = serializeToOptimizationProblem(builder.nodes, builder.edges);
      store.getState().setCanvasDisabled(exceedsCanvasScale(seeded));
      store.getState().hydrate(seeded, builder.documentName);
      store.getState().setProjectLoaded(true);
      return;
    }

    api
      .getProject(modelId, activeWorkspaceId ?? undefined)
      .then((project) => {
        if (cancelled) return;
        // A LATE-arriving initial load must not clobber edits made while the GET
        // was in flight (deep-link straight into a lens + immediate typing): the
        // in-memory draft is NEWER than the server's. Keep it and take only the
        // lock version, so the pending autosave can persist those edits. Scoped to
        // the first load — a deliberate workspace switch still re-hydrates.
        // Archived is this platform's soft delete and the server refuses every
        // write to an archived model. Read it on every load path, including the
        // early return below: without it the workbench opens as if the model
        // were live, and the first autosave comes back 409.
        store.getState().setArchived(project.status === "archived");

        const pre = store.getState();
        if (!firstLoadDone.current && (pre.headDirty || pre.dslDirty)) {
          firstLoadDone.current = true;
          pre.setLockVersion(project.draft_lock_version);
          store.getState().setProjectLoaded(true);
          return;
        }
        firstLoadDone.current = true;
        const modelJson = (project.draft_model_json ?? null) as OptimizationProblem | null;

        // Canvas-withheld guard, two causes with one treatment: a model too large
        // for the visual canvas (laying it out would freeze the tab) OR one the
        // canvas cannot represent EXACTLY (nonlinear/rich expressions — a partial
        // node view serialized back would silently corrupt the model, which is how
        // a Treasury model's balance rows once became `0 <= 0` in production).
        // Hydrate the canonical model DIRECTLY from model_json so Analyze/Solve
        // work, leave the canvas empty, and flag it so the Build lens shows a
        // notice and the bridge stays off.
        if (modelJson && (exceedsCanvasScale(modelJson) || !canvasCanRepresentModel(modelJson))) {
          const st = store.getState();
          // Disable the canvas bridge BEFORE touching the builder store: `reset()`
          // emits a change, and if the bridge is still "live" it would project the
          // now-empty canvas back onto the canonical model (empty), mark the draft
          // dirty, and let autosave OVERWRITE the imported model with nothing.
          st.setCanvasDisabled(true);
          useBuilderStore.getState().reset();
          useBuilderStore.setState({ documentId: project.id, documentName: project.name });
          st.hydrate(modelJson, project.name);
          st.setDraftDslSource(project.draft_dsl_source ?? "");
          st.setLockVersion(project.draft_lock_version);
          st.setProjectLoaded(true);
          return;
        }

        // Resolve the canvas to render: the stored canvas, else derive it from the
        // canonical model_json (so an API/ERP-created project that set only model_json
        // and no canvas still renders), else empty.
        const { nodes, edges } = resolveDraftCanvas(
          project.draft_canvas_json as { nodes?: unknown[]; edges?: unknown[] } | null,
          modelJson
        );

        if (nodes.length > 0) {
          useBuilderStore.getState().setDocument(project.id, project.name, nodes, edges);
        } else {
          useBuilderStore.getState().reset();
          useBuilderStore.setState({ documentId: project.id, documentName: project.name });
        }

        // Hydrate the canonical model from `serialize(canvas)` (not the cached
        // draft_model_json) so the canvas bridge's first pass is an idempotent
        // no-op — no spurious autosave on load. Store the draft lock for the
        // optimistic-concurrency `If-Match` on the next save.
        const current = useBuilderStore.getState();
        const st = store.getState();
        st.setCanvasDisabled(false);
        st.hydrate(
          serializeToOptimizationProblem(current.nodes, current.edges),
          project.name
        );
        st.setDraftDslSource(project.draft_dsl_source ?? "");
        st.setLockVersion(project.draft_lock_version);
        st.setProjectLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { status?: number })?.status;
        // A model that is gone gets a page saying so. It used to get a toast
        // and a push to the model list, which read as a click that had missed
        // — and on the Solve tab the push lost a race with the workspace, so
        // `/solve/<id>/history` painted tabs and a live Solve button over a
        // model the server answers 404 for.
        if (status === 404) {
          setMissing(true);
          return;
        }
        toast.error(tRef.current("loadFailed"));
        routerRef.current.push("/studio");
      });

    return () => {
      cancelled = true;
    };
    // router/t intentionally excluded — accessed via refs so a tab navigation does
    // not re-run the load (which would re-hydrate and drop unsaved in-memory edits).
  }, [modelId, activeWorkspaceId, store]);

  useCanvasBridge(store);
  useAutosave(store, modelId);
  useUnsavedGuard(store);
  // Drives the async solve from the store so it survives tab switches, and
  // reconciles a running/finished solve from the server on open (survives
  // reload / new tab / new device / power loss).
  useSolveSession(store, activeWorkspaceId ?? undefined);
  // Recompiles the JModel source when the active dataset changes, so picking a
  // dataset in Datos applies the model everywhere without visiting the lens.
  useActiveDatasetCompile(store);

  // After the hooks, never before them: an early return above would change the
  // hook order between the loading render and this one.
  if (missing) {
    return <MissingModel />;
  }

  return (
    <ModelProjectStoreContext.Provider value={store}>
      {/* The AI session lives here, above the tab panels, so an in-flight generation
          (and the produced model) survives switching sub-lens or Build/Analyze/Solve.
          It renders `children` (a stable element) so its per-delta re-renders never
          reach the workspace tree — only the Assistant lens consumes the context.
          The "Explain this model" session is lifted the same way, so an in-flight
          explanation survives leaving the Analyze tab and back. */}
      <StudioAssistantProvider store={store}>
        <ModelExplanationProvider projectId={modelId}>{children}</ModelExplanationProvider>
      </StudioAssistantProvider>
    </ModelProjectStoreContext.Provider>
  );
}
