"use client";

import { VersionModal } from "@/components/builder/VersionModal";
import { useBuilderStore } from "@/hooks/useBuilderStore";

interface VersionHistoryDrawerProps {
  documentId: string;
  isOpen: boolean;
  onClose: () => void;
  onRestore: (versionId: string) => void;
}

/**
 * Full version history + side-by-side diff + restore + naming. Reuses the builder's
 * `VersionModal` verbatim (list, search, named-only filter, structural diff, restore),
 * feeding it the live canvas so "diff vs current" is correct in the studio.
 */
export function VersionHistoryDrawer({
  documentId,
  isOpen,
  onClose,
  onRestore,
}: VersionHistoryDrawerProps) {
  const nodes = useBuilderStore((s) => s.nodes);
  const edges = useBuilderStore((s) => s.edges);

  return (
    <VersionModal
      documentId={documentId}
      isOpen={isOpen}
      onClose={onClose}
      onRestore={onRestore}
      currentCanvasJson={{ nodes, edges }}
    />
  );
}
