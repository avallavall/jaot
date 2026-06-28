"use client";

import { useParams } from "next/navigation";
import { WorkspaceShell } from "@/components/studio/WorkspaceShell";

/**
 * Per-model workspace layout. The shell (header + tab bar + live-stats rail) and
 * the shared model load live here, so they persist while only the active tab
 * panel swaps underneath.
 */
export default function ModelWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ modelId: string }>();
  const modelId = params?.modelId ?? "";

  return <WorkspaceShell modelId={modelId}>{children}</WorkspaceShell>;
}
