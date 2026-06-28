"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { ChevronLeft, Save, Sparkles, Play } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import { Button } from "@/components/ui/button";
import { StudioTabBar } from "./StudioTabBar";
import { LiveStatsPanel } from "./LiveStatsPanel";

interface WorkspaceShellProps {
  modelId: string;
  children: React.ReactNode;
}

/**
 * The persistent workspace chrome: header (model name + Commit/Explain/Solve),
 * the Build/Analyze/Solve tab bar, and the live-stats rail. Loads the model once
 * into the shared builder store so every tab is a lens on the same model.
 *
 * P0: the header actions are stubs (toast "coming soon"); versioning, explain
 * and solve are wired in later slices.
 */
export function WorkspaceShell({ modelId, children }: WorkspaceShellProps) {
  const t = useTranslations("studio");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const setDocument = useBuilderStore((s) => s.setDocument);
  const reset = useBuilderStore((s) => s.reset);
  const documentName = useBuilderStore((s) => s.documentName);

  useEffect(() => {
    if (!modelId || modelId === "new") {
      // Preserve content that a seeding flow may have placed in the store before
      // navigating here; otherwise start clean.
      const currentNodes = useBuilderStore.getState().nodes;
      const hasContent =
        currentNodes.length > 1 || currentNodes[0]?.type !== "objective";
      if (!hasContent) {
        reset();
      }
      return;
    }

    api
      .getBuilderDocument(modelId, activeWorkspaceId ?? undefined)
      .then((doc) => {
        const canvasJson = doc.canvas_json as
          | { nodes?: unknown[]; edges?: unknown[] }
          | null;
        const nodes = Array.isArray(canvasJson?.nodes)
          ? (canvasJson!.nodes as BuilderNode[])
          : [];
        const edges = Array.isArray(canvasJson?.edges)
          ? (canvasJson!.edges as BuilderEdge[])
          : [];

        if (nodes.length > 0) {
          setDocument(doc.id, doc.name, nodes, edges);
        } else {
          reset();
          useBuilderStore.setState({ documentId: doc.id, documentName: doc.name });
        }
      })
      .catch((err: unknown) => {
        const apiErr = err as { status?: number };
        toast.error(apiErr?.status === 404 ? t("notFound") : t("loadFailed"));
        router.push("/studio");
      });
  }, [modelId, activeWorkspaceId, setDocument, reset, router, t]);

  const comingSoon = () => toast(t("comingSoon"));

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <Link
            href="/studio"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ChevronLeft className="h-4 w-4" />
            {t("backToModels")}
          </Link>
          <span className="text-muted-foreground" aria-hidden="true">
            /
          </span>
          <span className="font-medium truncate">
            {documentName || t("untitled")}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={comingSoon}>
            <Save className="h-4 w-4 mr-1" />
            {t("headerCommit")}
          </Button>
          <Button variant="outline" size="sm" onClick={comingSoon}>
            <Sparkles className="h-4 w-4 mr-1" />
            {t("headerExplain")}
          </Button>
          <Button size="sm" onClick={comingSoon}>
            <Play className="h-4 w-4 mr-1" />
            {t("headerSolve")}
          </Button>
        </div>
      </header>

      <StudioTabBar modelId={modelId} />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="flex flex-1 min-w-0 flex-col overflow-hidden">
          {children}
        </div>
        <LiveStatsPanel />
      </div>
    </div>
  );
}
