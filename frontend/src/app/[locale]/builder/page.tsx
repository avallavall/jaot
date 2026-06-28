"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { BuilderDocumentListItem } from "@/lib/types";
import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
import { parseModelFile } from "@/lib/builder/import-model";
import { getErrorMessage } from "@/lib/errors";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useAuth } from "@/contexts/AuthContext";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FileEdit } from "lucide-react";
import { EmptyState } from "@/components/guidance/EmptyState";
import { useTranslations } from "next-intl";

function useFormatDate() {
  const t = useTranslations("builder");
  return (dateStr: string): string => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return t("list.today");
    if (diffDays === 1) return t("list.yesterday");
    if (diffDays < 7) return t("list.daysAgo", { count: diffDays });
    return date.toLocaleDateString();
  };
}

function DocumentCard({
  doc,
  onOpen,
  onDelete,
  canDelete,
}: {
  doc: BuilderDocumentListItem;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  canDelete: boolean;
}) {
  const t = useTranslations("builder");
  const formatDate = useFormatDate();
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!canDelete) return;
    const confirmed = window.confirm(t("list.deleteConfirm", { name: doc.name }));
    if (!confirmed) return;

    setIsDeleting(true);
    try {
      await onDelete(doc.id);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div
      className="group relative border rounded-lg p-4 bg-card hover:border-primary/50 hover:shadow-sm cursor-pointer transition-all"
      onClick={() => onOpen(doc.id)}
    >
      <div className="h-24 bg-muted rounded-md mb-3 flex items-center justify-center">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-muted-foreground/50"
        >
          <circle cx="12" cy="5" r="2" />
          <circle cx="5" cy="19" r="2" />
          <circle cx="19" cy="19" r="2" />
          <line x1="12" y1="7" x2="5" y2="17" />
          <line x1="12" y1="7" x2="19" y2="17" />
        </svg>
      </div>

      <h3 className="font-medium text-sm truncate">{doc.name}</h3>
      <p className="text-xs text-muted-foreground mt-0.5">
        {t("list.updated", { date: formatDate(doc.updated_at) })}
      </p>

      {/* Delete button (visible on hover) */}
      {canDelete && (
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all"
          title={t("list.deleteDocument")}
          aria-label={t("list.deleteDocument")}
        >
          {isDeleting ? (
            <span className="text-xs">...</span>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
              <path d="M10 11v6M14 11v6" />
            </svg>
          )}
        </button>
      )}
    </div>
  );
}

export default function BuilderHomePage() {
  const t = useTranslations("builder");
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const setDocument = useBuilderStore((s) => s.setDocument);
  const reset = useBuilderStore((s) => s.reset);
  const { activeWorkspaceId } = useAuth();
  const canCreate = useWorkspacePermission("solver");
  const canEdit = useWorkspacePermission("editor");
  const roleName = useRoleDisplayName();

  const [documents, setDocuments] = useState<BuilderDocumentListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await api.listBuilderDocuments(activeWorkspaceId ?? undefined);
      setDocuments(docs);
    } catch {
      // If auth fails silently, show empty state (user needs to log in)
      setDocuments([]);
    } finally {
      setIsLoading(false);
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleNewModel = useCallback(() => {
    reset();
    router.push("/builder/new");
  }, [reset, router]);

  const handleOpenDocument = useCallback(
    (id: string) => {
      const href = activeWorkspaceId
        ? `/builder/${id}?workspace_id=${activeWorkspaceId}`
        : `/builder/${id}`;
      router.push(href);
    },
    [router, activeWorkspaceId]
  );

  const handleDeleteDocument = useCallback(
    async (id: string) => {
      try {
        await api.deleteBuilderDocument(id, activeWorkspaceId ?? undefined);
        setDocuments((prev) => prev.filter((d) => d.id !== id));
        toast.success(t("list.documentDeleted"));
      } catch {
        toast.error(t("list.deleteFailed"));
      }
    },
    [activeWorkspaceId, t]
  );

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // Reset input so the same file can be re-imported.
      e.target.value = "";
      if (!file) return;

      try {
        const { problem, baseName } = await parseModelFile(file);

        if (!problem.variables || !problem.objective) {
          toast.error(t("list.importInvalid"));
          return;
        }

        const { nodes, edges } = deserializeFromOptimizationProblem(problem);
        reset();
        setDocument("new", baseName, nodes, edges);
        router.push("/builder/new");
        toast.success(t("list.importSuccess", { count: nodes.length }));
      } catch (err) {
        toast.error(getErrorMessage(err, t("list.importParseFailed")));
      }
    },
    [reset, setDocument, router, t]
  );

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{t("list.title")}</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {t("list.subtitle")}
          </p>
        </div>
        <TooltipProvider>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleImportClick}>
              {t("list.importModel")}
            </Button>
            <Button onClick={() => router.push("/builder/templates")}>
              {t("list.templates")}
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button onClick={handleNewModel} disabled={!canCreate}>
                    {t("list.newModel")}
                  </Button>
                </span>
              </TooltipTrigger>
              {!canCreate && (
                <TooltipContent className="max-w-xs text-center">
                  {t("list.noPermission", { role: roleName })}
                </TooltipContent>
              )}
            </Tooltip>
          </div>
        </TooltipProvider>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".json,.mps,.lp,.cip,.gz,application/json"
        onChange={handleFileChange}
        className="hidden"
        aria-hidden="true"
      />

      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="border rounded-lg p-4 space-y-2">
              <Skeleton className="h-24 w-full rounded-md" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))}
        </div>
      ) : documents.length === 0 ? (
        <EmptyState
          icon={<FileEdit className="h-12 w-12" />}
          title={t("list.emptyTitle")}
          description={t("list.emptyDescription")}
          expertDescription={t("list.emptyExpertDescription")}
          actionLabel={t("list.emptyAction")}
          actionHref="/builder/new"
          secondaryActionLabel={t("list.emptySecondaryAction")}
          secondaryActionHref="/builder/ai-assistant"
          skillLevelCTAs={{
            beginner: {
              actionLabel: t("list.browseTemplates"),
              actionHref: "/builder/templates",
              secondaryActions: [
                { label: t("list.emptySecondaryAction"), href: "/builder/ai-assistant" },
              ],
            },
            intermediate: {
              actionLabel: t("list.emptySecondaryAction"),
              actionHref: "/builder/ai-assistant",
              secondaryActions: [
                { label: t("list.browseTemplates"), href: "/builder/templates" },
                { label: t("list.emptyAction"), href: "/builder/new" },
              ],
            },
            expert: {
              actionLabel: t("list.emptyAction"),
              actionHref: "/builder/new",
              secondaryActions: [
                { label: t("list.emptySecondaryAction"), href: "/builder/ai-assistant" },
              ],
            },
          }}
        />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
          {documents.map((doc) => (
            <DocumentCard
              key={doc.id}
              doc={doc}
              onOpen={handleOpenDocument}
              onDelete={handleDeleteDocument}
              canDelete={canEdit}
            />
          ))}
        </div>
      )}
    </div>
  );
}
