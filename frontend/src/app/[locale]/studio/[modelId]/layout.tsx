"use client";

import { useParams } from "next/navigation";
import { ModelProjectStoreProvider } from "@/components/studio/store/ModelProjectStoreProvider";
import { WorkspaceShell } from "@/components/studio/WorkspaceShell";

/**
 * Per-model workspace layout. The canonical model store, the shell (header + tab
 * bar + live-stats rail) and the loaded model live here, so they persist while
 * only the active tab panel swaps underneath. Keyed by `modelId` so navigating
 * between models yields a fresh store.
 */
export default function ModelWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ modelId: string }>();
  const modelId = params?.modelId ?? "";

  return (
    <ModelProjectStoreProvider key={modelId} modelId={modelId}>
      <WorkspaceShell>{children}</WorkspaceShell>
    </ModelProjectStoreProvider>
  );
}
