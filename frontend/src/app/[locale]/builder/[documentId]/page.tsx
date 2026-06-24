"use client";

import { useEffect, useState, Suspense } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { BuilderToolbar } from "@/components/builder/BuilderToolbar";
import { NodePalette } from "@/components/builder/NodePalette";
import { PropertiesPanel } from "@/components/builder/PropertiesPanel";
import {
  BuilderOnboarding,
  useBuilderOnboarding,
} from "@/components/builder/BuilderOnboarding";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useAuth } from "@/contexts/AuthContext";
import { WorkspaceBreadcrumb } from "@/components/layout/WorkspaceBreadcrumb";
import { useTranslations } from "next-intl";
import {
  useWorkspaceScopeGuard,
  WorkspaceSwitchPrompt,
} from "@/components/workspace/WorkspaceSwitchPrompt";
import { api } from "@/lib/api";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";

// Import canvas with SSR disabled — ReactFlow requires browser APIs
const BuilderCanvas = dynamic(
  () =>
    import("@/components/builder/BuilderCanvas").then((m) => m.BuilderCanvas),
  { ssr: false }
);

function LoadingSkeleton() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center space-y-3">
        <div className="h-8 w-48 bg-muted rounded animate-pulse mx-auto" />
        <div className="h-4 w-32 bg-muted rounded animate-pulse mx-auto" />
      </div>
    </div>
  );
}

function BuilderDocumentPageInner() {
  const t = useTranslations("builder");
  const params = useParams<{ documentId: string }>();
  const documentId = params?.documentId ?? "new";
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlWorkspaceId = searchParams.get("workspace_id");
  const { activeWorkspaceId } = useAuth();

  const selectedNodeId = useBuilderStore((s) => s.selectedNodeId);
  const setDocument = useBuilderStore((s) => s.setDocument);
  const reset = useBuilderStore((s) => s.reset);
  const documentName = useBuilderStore((s) => s.documentName);

  const [isLoading, setIsLoading] = useState(documentId !== "new");

  // Onboarding tutorial for first-time users
  const {
    isVisible: onboardingVisible,
    instanceKey: onboardingKey,
    restart: restartOnboarding,
    dismiss: dismissOnboarding,
  } = useBuilderOnboarding();

  // Workspace scope guard — prompts if URL workspace differs from active
  const { showPrompt, targetWorkspaceName, handleAccept, handleDecline } =
    useWorkspaceScopeGuard(urlWorkspaceId);

  useEffect(() => {
    if (documentId === "new") {
      // Only reset if the store doesn't already have imported content
      // (e.g., from Import JSON which sets nodes before navigating here)
      const currentNodes = useBuilderStore.getState().nodes;
      const hasImportedContent = currentNodes.length > 1 || currentNodes[0]?.type !== "objective";
      if (!hasImportedContent) {
        reset();
      }
      return;
    }

    api
      .getBuilderDocument(documentId, activeWorkspaceId ?? undefined)
      .then((doc) => {
        // Restore nodes and edges from canvas_json if present
        const canvasJson = doc.canvas_json as { nodes?: unknown[]; edges?: unknown[] } | null;
        const restoredNodes =
          Array.isArray(canvasJson?.nodes) ? (canvasJson!.nodes as BuilderNode[]) : [];
        const restoredEdges =
          Array.isArray(canvasJson?.edges) ? (canvasJson!.edges as BuilderEdge[]) : [];

        if (restoredNodes.length > 0) {
          setDocument(doc.id, doc.name, restoredNodes, restoredEdges);
        } else {
          // Empty canvas_json — start fresh with the document ID/name set
          reset();
          useBuilderStore.setState({ documentId: doc.id, documentName: doc.name });
        }
      })
      .catch((err: unknown) => {
        const apiErr = err as { status?: number };
        if (apiErr?.status === 404) {
          toast.error(t("chat.documentNotFound"));
          router.push("/builder");
        } else {
          toast.error(t("chat.documentLoadFailed"));
          router.push("/builder");
        }
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [documentId, activeWorkspaceId, setDocument, reset, router, t]);

  return (
    <>
      <div className="px-4 pt-2">
        <WorkspaceBreadcrumb
          section={t("chat.breadcrumbSection")}
          sectionHref="/builder"
          itemName={documentName || undefined}
        />
      </div>
      <BuilderToolbar documentId={documentId} onHelpClick={restartOnboarding} />
      <div className="flex flex-1 overflow-hidden">
        <NodePalette />
        {isLoading ? <LoadingSkeleton /> : <BuilderCanvas />}
        {selectedNodeId && <PropertiesPanel />}
      </div>
      <WorkspaceSwitchPrompt
        open={showPrompt}
        workspaceName={targetWorkspaceName}
        onAccept={handleAccept}
        onDecline={handleDecline}
      />
      <BuilderOnboarding
        key={onboardingKey}
        isVisible={onboardingVisible}
        onDismiss={dismissOnboarding}
      />
    </>
  );
}

export default function BuilderDocumentPage() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <BuilderDocumentPageInner />
    </Suspense>
  );
}
