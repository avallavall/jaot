"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useBuilderStore, useTemporalStore } from "@/hooks/useBuilderStore";
import { useShallow } from "zustand/react/shallow";
import { useReactFlow } from "@xyflow/react";
import { useAuth } from "@/contexts/AuthContext";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Sparkles } from "lucide-react";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import { ExportModelButton } from "@/components/solve/ExportModelButton";
import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
import { parseModelFile } from "@/lib/builder/import-model";
import { diffCanvasJson } from "@/lib/builder/diff";
import { api } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import type { SolveResult, OptimizationProblem } from "@/lib/types";
import { SolveResultsDrawer } from "./SolveResultsDrawer";
import { VersionDropdown } from "./VersionDropdown";
import { VersionModal } from "./VersionModal";
import { SaveIndicator } from "./SaveIndicator";
import { ModelHealthBadge } from "./ModelHealthBadge";
import { useSaveIndicator } from "@/hooks/useSaveIndicator";
import { useTranslations } from "next-intl";

interface BuilderToolbarProps {
  readonly documentId: string;
  readonly onHelpClick?: () => void;
}

export function BuilderToolbar({ documentId, onHelpClick }: BuilderToolbarProps) {
  const t = useTranslations("builder");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const canEdit = useWorkspacePermission("editor");
  const canSolve = useWorkspacePermission("solver");
  const roleName = useRoleDisplayName();
  const [isSolving, setIsSolving] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [solveResult, setSolveResult] = useState<SolveResult | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [versionModalOpen, setVersionModalOpen] = useState(false);
  const [saveCounter, setSaveCounter] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [restoreVersionId, setRestoreVersionId] = useState<string | null>(null);
  const [restoreDiffSummary, setRestoreDiffSummary] = useState<string>("");
  const [isRestoring, setIsRestoring] = useState(false);

  const { documentName, documentId: storeDocId, nodes, edges, setDocument } = useBuilderStore(
    useShallow((s) => ({
      documentName: s.documentName,
      documentId: s.documentId,
      nodes: s.nodes,
      edges: s.edges,
      setDocument: s.setDocument,
    }))
  );
  const { undo, redo, pastStates, futureStates } = useTemporalStore();
  const reactFlowInstance = useReactFlow();
  const { fitView, zoomIn, zoomOut } = reactFlowInstance;

  const {
    state: saveState,
    lastSavedAt,
    markUnsaved,
    markSaving,
    markSaved,
    markError,
  } = useSaveIndicator();
  const isInitialLoadRef = useRef(true);
  const prevNodesRef = useRef(nodes);
  const prevEdgesRef = useRef(edges);
  const prevNameRef = useRef(documentName);

  // Mark unsaved on canvas/name changes; skip first change after mount (initial document load).
  useEffect(() => {
    const nodesChanged = prevNodesRef.current !== nodes;
    const edgesChanged = prevEdgesRef.current !== edges;
    const nameChanged = prevNameRef.current !== documentName;

    prevNodesRef.current = nodes;
    prevEdgesRef.current = edges;
    prevNameRef.current = documentName;

    if (!nodesChanged && !edgesChanged && !nameChanged) return;

    if (isInitialLoadRef.current) {
      isInitialLoadRef.current = false;
      return;
    }

    markUnsaved();
  }, [nodes, edges, documentName, markUnsaved]);

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    useBuilderStore.setState({ documentName: e.target.value });
  };

  const handleSolve = useCallback(async () => {
    const varNodes = nodes.filter((n) => n.type === "variable");
    const objNode = nodes.find((n) => n.type === "objective");

    if (varNodes.length === 0) {
      toast.error(t("toolbar.addVariableFirst"));
      return;
    }
    if (!objNode) {
      toast.error(t("toolbar.objectiveRequired"));
      return;
    }

    const objEdges = edges.filter((e) => e.target === objNode.id);
    if (objEdges.length === 0) {
      toast.error(t("toolbar.connectToObjective"));
      return;
    }

    setIsSolving(true);
    try {
      const problem = serializeToOptimizationProblem(nodes, edges);
      const docId = storeDocId ?? (documentId !== "new" ? documentId : null);
      const result = await api.solve(problem, activeWorkspaceId ?? undefined, {
        origin: "visual_builder",
        sourceKind: "builder_document",
        sourceId: docId,
      });
      setSolveResult(result);
      setDrawerOpen(true);
    } catch (err: unknown) {
      const status = getErrorStatus(err);
      if (status === 402) {
        toast.error(t("toolbar.insufficientCredits"));
      } else if (status === 422) {
        toast.error(t("toolbar.invalidProblem", { message: getErrorMessage(err, t("toolbar.checkModelDefinition")) }));
      } else if (status && status >= 500) {
        toast.error(t("toolbar.solverError", { detail: getErrorMessage(err, t("toolbar.checkModelDefinition")) }));
      } else {
        toast.error(getErrorMessage(err, t("toolbar.solveFailed")));
      }
    } finally {
      setIsSolving(false);
    }
  }, [nodes, edges, activeWorkspaceId, storeDocId, documentId, t]);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    markSaving();
    try {
      const canvas_json = {
        nodes: nodes.map((n) => ({ ...n })),
        edges: edges.map((e) => ({ ...e })),
      };

      let problem: OptimizationProblem | null = null;
      try {
        problem = serializeToOptimizationProblem(nodes, edges);
      } catch {
        // model_json is optional — don't block save
      }

      const model_json = problem ? (problem as unknown as Record<string, unknown>) : null;

      const wsId = activeWorkspaceId ?? undefined;
      let savedId = storeDocId;

      if (!savedId || documentId === "new") {
        const created = await api.createBuilderDocument(documentName, wsId);
        savedId = created.id;

        await api.updateBuilderDocument(savedId, {
          name: documentName,
          canvas_json,
          ...(model_json ? { model_json } : {}),
        }, wsId);

        useBuilderStore.setState({ documentId: savedId });

        const newUrl = activeWorkspaceId
          ? `/builder/${savedId}?workspace_id=${activeWorkspaceId}`
          : `/builder/${savedId}`;
        router.push(newUrl);
      } else {
        await api.updateBuilderDocument(savedId, {
          name: documentName,
          canvas_json,
          ...(model_json ? { model_json } : {}),
        }, wsId);
      }

      // Best-effort version checkpoint after save — failures must not block.
      const finalSavedId = savedId;
      if (finalSavedId) {
        const canvasSnapshot = {
          nodes: nodes.map((n) => ({ ...n })),
          edges: edges.map((e) => ({ ...e })),
        };
        api
          .createVersion(finalSavedId, { canvas_json: canvasSnapshot }, wsId)
          .then(() => {
            setSaveCounter((c) => c + 1);
          })
          .catch(() => { /* ignore */ });
      }

      markSaved();
      toast.success(t("toolbar.modelSaved"));
    } catch (err: unknown) {
      markError();
      toast.error(getErrorMessage(err, t("toolbar.saveFailed")));
    } finally {
      setIsSaving(false);
    }
  }, [nodes, edges, storeDocId, documentId, documentName, router, activeWorkspaceId, markSaving, markSaved, markError, t]);

  const handleRestore = useCallback(
    async (versionId: string) => {
      const effectiveDocId = storeDocId ?? documentId;
      if (!effectiveDocId || effectiveDocId === "new") {
        toast.error(t("toolbar.saveBeforeRestore"));
        return;
      }

      try {
        const currentCanvas = {
          nodes: nodes.map((n) => ({ ...n })),
          edges: edges.map((e) => ({ ...e })),
        };
        const targetVersion = await api.getVersion(effectiveDocId, versionId, activeWorkspaceId ?? undefined);
        const targetCanvas = targetVersion.canvas_json as { nodes?: unknown[]; edges?: unknown[] };
        const diff = diffCanvasJson(currentCanvas, targetCanvas);

        setRestoreVersionId(versionId);
        setRestoreDiffSummary(diff.summary);
        setRestoreConfirmOpen(true);
      } catch {
        toast.error(t("toolbar.loadVersionFailed"));
      }
    },
    [storeDocId, documentId, nodes, edges, activeWorkspaceId, t]
  );

  const confirmRestore = useCallback(async () => {
    const effectiveDocId = storeDocId ?? documentId;
    if (!restoreVersionId || !effectiveDocId) return;

    setIsRestoring(true);
    try {
      const currentCanvas = {
        nodes: nodes.map((n) => ({ ...n })),
        edges: edges.map((e) => ({ ...e })),
      };

      // Backend auto-checkpoints current state before applying target.
      const result = await api.restoreVersion(effectiveDocId, restoreVersionId, {
        current_canvas_json: currentCanvas,
      }, activeWorkspaceId ?? undefined);

      const restored = result.document.canvas_json as { nodes?: unknown[]; edges?: unknown[] };
      setDocument(
        result.document.id,
        result.document.name,
        (restored.nodes ?? []) as Parameters<typeof setDocument>[2],
        (restored.edges ?? []) as Parameters<typeof setDocument>[3]
      );

      setTimeout(() => {
        fitView({ padding: 0.2 });
      }, 100);

      setSaveCounter((c) => c + 1);

      toast.success(t("toolbar.restoreSuccess"));
      setRestoreConfirmOpen(false);
      setVersionModalOpen(false);
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("toolbar.restoreFailed")));
    } finally {
      setIsRestoring(false);
    }
  }, [restoreVersionId, storeDocId, documentId, nodes, edges, setDocument, fitView, activeWorkspaceId, t]);

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const applyImportedProblem = useCallback(
    (problem: OptimizationProblem, baseName: string) => {
      if (!problem.variables || !problem.objective) {
        toast.error(t("toolbar.importInvalid"));
        return;
      }

      const { nodes: importedNodes, edges: importedEdges } =
        deserializeFromOptimizationProblem(problem);

      useBuilderStore.getState().reset();
      setDocument("new", baseName, importedNodes, importedEdges);

      if (documentId === "new") {
        // Already on /builder/new — force ReactFlow to pick up new nodes.
        reactFlowInstance.setNodes(importedNodes);
        reactFlowInstance.setEdges(importedEdges);
        setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 50);
      } else {
        router.push("/builder/new");
      }

      toast.success(t("toolbar.importSuccess", { count: importedNodes.length }));
    },
    [setDocument, router, documentId, reactFlowInstance, t]
  );

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // Reset input so the same file can be re-imported.
      e.target.value = "";
      if (!file) return;

      try {
        const { problem, baseName } = await parseModelFile(file);
        applyImportedProblem(problem, baseName);
      } catch (err) {
        toast.error(getErrorMessage(err, t("toolbar.importParseFailed")));
      }
    },
    [applyImportedProblem, t]
  );

  const effectiveDocId = storeDocId ?? (documentId !== "new" ? documentId : null);

  return (
    <>
      <TooltipProvider>
      <div className="h-14 border-b bg-background flex items-center px-4 gap-2 shrink-0">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/builder")}
          title={t("toolbar.backToModels")}
          className="h-8 w-8 p-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
        </Button>

        <Separator orientation="vertical" className="h-6" />

        <Input
          value={documentName}
          onChange={handleNameChange}
          className="w-48 h-8 text-sm font-medium border-transparent hover:border-border focus:border-primary"
          placeholder={t("toolbar.untitledModel")}
        />

        <SaveIndicator state={saveState} lastSavedAt={lastSavedAt} />

        <ModelHealthBadge />

        <Separator orientation="vertical" className="h-6" />

        <Button
          variant="ghost"
          size="sm"
          onClick={() => undo()}
          disabled={pastStates.length === 0}
          title={t("toolbar.undoTooltip")}
          className="h-8 w-8 p-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/></svg>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => redo()}
          disabled={futureStates.length === 0}
          title={t("toolbar.redoTooltip")}
          className="h-8 w-8 p-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13"/></svg>
        </Button>

        <Separator orientation="vertical" className="h-6" />

        <Button
          variant="ghost"
          size="sm"
          onClick={() => zoomIn()}
          title={t("toolbar.zoomIn")}
          className="h-8 w-8 p-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => zoomOut()}
          title={t("toolbar.zoomOut")}
          className="h-8 w-8 p-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => fitView({ padding: 0.2 })}
          title={t("toolbar.fitView")}
          className="h-8 w-8 p-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>
        </Button>

        <Separator orientation="vertical" className="h-6" />

        <Button
          variant="ghost"
          size="sm"
          onClick={handleImportClick}
          title={t("toolbar.importModelTooltip")}
          className="h-8 px-2 text-xs"
        >
          {t("toolbar.import")}
        </Button>

        <ExportModelButton
          getProblem={() => {
            try {
              return serializeToOptimizationProblem(nodes, edges);
            } catch {
              return null;
            }
          }}
          filenameBase={documentName || "model"}
          variant="ghost"
          disabled={nodes.length === 0}
        />

        {effectiveDocId && (
          <VersionDropdown
            documentId={effectiveDocId}
            saveCounter={saveCounter}
            onViewAll={() => setVersionModalOpen(true)}
            onRestore={handleRestore}
          />
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.mps,.lp,.cip,.gz,application/json"
          onChange={handleFileChange}
          className="hidden"
          aria-hidden="true"
        />

        <div className="flex-1" />

        {onHelpClick && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={onHelpClick}
                className="h-8 w-8 p-0"
                aria-label={t("toolbar.helpTutorial")}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("toolbar.helpTutorial")}</TooltipContent>
          </Tooltip>
        )}

        <Separator orientation="vertical" className="h-6" />

        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            const docId = storeDocId ?? (documentId !== "new" ? documentId : null);
            if (docId) {
              router.push(`/builder/${docId}/chat`);
            } else {
              toast.info(t("toolbar.saveFirst"));
            }
          }}
          className="h-8 gap-1.5 text-xs"
        >
          <Sparkles className="w-3.5 h-3.5" />
          {t("toolbar.aiAssistant")}
        </Button>

        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleSave}
                disabled={isSaving || !canEdit}
              >
                {isSaving ? t("toolbar.saving") : t("toolbar.save")}
              </Button>
            </span>
          </TooltipTrigger>
          {!canEdit && (
            <TooltipContent className="max-w-xs text-center">
              {t("toolbar.noEditPermission", { role: roleName })}
            </TooltipContent>
          )}
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <span data-onboarding-target="solve">
              <Button
                size="sm"
                onClick={handleSolve}
                disabled={isSolving || !canSolve}
              >
                {isSolving ? t("toolbar.solving") : t("toolbar.solve")}
              </Button>
            </span>
          </TooltipTrigger>
          {!canSolve && (
            <TooltipContent className="max-w-xs text-center">
              {t("toolbar.noSolvePermission", { role: roleName })}
            </TooltipContent>
          )}
        </Tooltip>
      </div>
      </TooltipProvider>

      <SolveResultsDrawer
        result={solveResult}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />

      {effectiveDocId && (
        <VersionModal
          documentId={effectiveDocId}
          isOpen={versionModalOpen}
          onClose={() => setVersionModalOpen(false)}
          onRestore={handleRestore}
          currentCanvasJson={{ nodes, edges }}
        />
      )}

      <Dialog
        open={restoreConfirmOpen}
        onOpenChange={(open) => {
          if (!open) {
            setRestoreConfirmOpen(false);
            setRestoreVersionId(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("toolbar.restoreTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              {t("toolbar.restoreDescription")}
            </p>
            <p className="rounded-md bg-muted px-3 py-2 text-xs font-mono">
              {restoreDiffSummary}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("toolbar.restoreAutoSave")}
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setRestoreConfirmOpen(false);
                setRestoreVersionId(null);
              }}
              disabled={isRestoring}
            >
              Cancel
            </Button>
            <Button size="sm" onClick={confirmRestore} disabled={isRestoring}>
              {isRestoring ? t("toolbar.restoring") : t("toolbar.restore")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
