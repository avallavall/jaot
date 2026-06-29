"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import type { OptimizationProblem } from "@/lib/types";
import {
  createModelProjectStore,
  type ModelProjectStore,
} from "./createModelProjectStore";
import { ModelProjectStoreContext } from "./useModelProjectStore";
import { useCanvasBridge } from "./useCanvasBridge";
import { useAutosave } from "./useAutosave";

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

  // Lazy one-time init (the provider is keyed by modelId, so a fresh model gets a
  // fresh store). useState — not useRef — so the store is not read during render.
  const [store] = useState<ModelProjectStore>(() =>
    createModelProjectStore({
      modelId,
      name: "Untitled Model",
      problem: EMPTY_PROBLEM,
    })
  );

  useEffect(() => {
    let cancelled = false;
    const builder = useBuilderStore.getState();

    if (!modelId || modelId === "new") {
      // Seeded by a launcher flow (or empty): derive canonical from current canvas.
      store
        .getState()
        .hydrate(
          serializeToOptimizationProblem(builder.nodes, builder.edges),
          builder.documentName
        );
      return;
    }

    api
      .getProject(modelId, activeWorkspaceId ?? undefined)
      .then((project) => {
        if (cancelled) return;
        const canvasJson = project.draft_canvas_json as
          | { nodes?: unknown[]; edges?: unknown[] }
          | null;
        const nodes = Array.isArray(canvasJson?.nodes)
          ? (canvasJson!.nodes as BuilderNode[])
          : [];
        const edges = Array.isArray(canvasJson?.edges)
          ? (canvasJson!.edges as BuilderEdge[])
          : [];

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
        st.hydrate(
          serializeToOptimizationProblem(current.nodes, current.edges),
          project.name
        );
        st.setLockVersion(project.draft_lock_version);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { status?: number })?.status;
        toast.error(status === 404 ? t("notFound") : t("loadFailed"));
        router.push("/studio");
      });

    return () => {
      cancelled = true;
    };
  }, [modelId, activeWorkspaceId, router, t, store]);

  useCanvasBridge(store);
  useAutosave(store, modelId);

  return (
    <ModelProjectStoreContext.Provider value={store}>
      {children}
    </ModelProjectStoreContext.Provider>
  );
}
