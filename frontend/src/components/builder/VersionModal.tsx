"use client";

import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { Bookmark, Search, Filter } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from "@/components/ui/context-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ModelVersion, ModelVersionListItem } from "@/lib/types";
import { diffCanvasJson } from "@/lib/builder/diff";
import type { CanvasDiff, NodeChange } from "@/lib/builder/diff";
import { useTranslations } from "next-intl";

function formatRelativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.floor((now - then) / 1000);

  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} day(s) ago`;
  return new Date(dateStr).toLocaleDateString();
}

function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value || "(empty)";
  return JSON.stringify(value);
}

interface VersionModalProps {
  documentId: string;
  isOpen: boolean;
  onClose: () => void;
  onRestore: (versionId: string) => void;
  currentCanvasJson: { nodes?: unknown[]; edges?: unknown[] };
}

function DiffPanel({ diff }: { diff: CanvasDiff | null }) {
  const t = useTranslations("builder");
  if (!diff) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
        {t("versions.selectVersion")}
      </div>
    );
  }

  if (diff.isEmpty) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
        {t("versions.noChanges")}
      </div>
    );
  }

  const renderChangeBadge = (type: NodeChange["type"]) => {
    if (type === "added")
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-xs bg-[var(--status-optimal-bg)] text-[var(--status-optimal-text)] font-medium">
          {t("versions.added")}
        </span>
      );
    if (type === "removed")
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-xs bg-[var(--status-infeasible-bg)] text-[var(--status-infeasible-text)] font-medium">
          {t("versions.removed")}
        </span>
      );
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-xs bg-[var(--status-timelimit-bg)] text-[var(--status-timelimit-text)] font-medium">
        {t("versions.modified")}
      </span>
    );
  };

  const sections = [
    { title: t("versions.variables"), changes: diff.variables },
    { title: t("versions.constraints"), changes: diff.constraints },
    { title: t("versions.objectiveSection"), changes: diff.objective },
  ];

  return (
    <div className="space-y-4 text-sm">
      <p className="text-xs text-muted-foreground border-b pb-2">{diff.summary}</p>
      {sections.map((section) => {
        if (section.changes.length === 0) return null;
        return (
          <div key={section.title}>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              {section.title}
            </h4>
            <div className="space-y-2">
              {section.changes.map((change) => (
                <div
                  key={change.nodeId}
                  className="rounded-md border p-2 space-y-1"
                >
                  <div className="flex items-center gap-2">
                    {renderChangeBadge(change.type)}
                    <span className="font-medium text-xs">{change.nodeName}</span>
                  </div>
                  {change.fields && change.fields.length > 0 && (
                    <ul className="pl-2 space-y-0.5">
                      {change.fields.map((fc) => (
                        <li key={fc.field} className="text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">{fc.field}:</span>{" "}
                          <span className="line-through opacity-60">
                            {formatFieldValue(fc.from)}
                          </span>{" "}
                          <span>→ {formatFieldValue(fc.to)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
      {diff.edges.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            {t("versions.connections")}
          </h4>
          <div className="space-y-2">
            {diff.edges.map((edge) => (
              <div key={edge.edgeId} className="rounded-md border p-2 space-y-1">
                <div className="flex items-center gap-2">
                  {renderChangeBadge(edge.type)}
                  <span className="text-xs font-medium">
                    {edge.sourceNode} → {edge.targetNode}
                  </span>
                </div>
                {edge.fields && edge.fields.length > 0 && (
                  <ul className="pl-2 space-y-0.5">
                    {edge.fields.map((fc) => (
                      <li key={fc.field} className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{fc.field}:</span>{" "}
                        <span className="line-through opacity-60">
                          {formatFieldValue(fc.from)}
                        </span>{" "}
                        <span>→ {formatFieldValue(fc.to)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface NameVersionDialogProps {
  versionId: string | null;
  documentId: string;
  onClose: () => void;
  onSuccess: (updated: ModelVersion) => void;
}

function NameVersionDialog({ versionId, documentId, onClose, onSuccess }: NameVersionDialogProps) {
  const t = useTranslations("builder");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!versionId || !name.trim()) return;
    setIsSaving(true);
    try {
      const updated = await api.promoteVersion(documentId, versionId, {
        version_name: name.trim(),
        version_description: description.trim() || undefined,
      });
      onSuccess(updated);
      onClose();
    } catch (err) {
      console.warn('Failed to save version:', err);
      toast.error(t("versions.saveVersionFailed"));
    } finally {
      setIsSaving(false);
    }
  }, [versionId, documentId, name, description, onSuccess, onClose, t]);

  if (!versionId) return null;

  return (
    <Dialog open={!!versionId} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("versions.nameVersion")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div>
            <label htmlFor="version-name" className="text-xs font-medium text-muted-foreground block mb-1">
              {t("versions.nameLabel")}
            </label>
            <Input
              id="version-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("versions.namePlaceholder")}
              onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
            />
          </div>
          <div>
            <label htmlFor="version-description" className="text-xs font-medium text-muted-foreground block mb-1">
              {t("versions.descriptionLabel")}
            </label>
            <Input
              id="version-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("versions.descriptionPlaceholder")}
            />
          </div>
          <div className="flex gap-2 justify-end pt-1">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleSave} disabled={!name.trim() || isSaving}>
              {isSaving ? t("toolbar.saving") : t("versions.saveName")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function VersionModal({
  documentId,
  isOpen,
  onClose,
  onRestore,
  currentCanvasJson,
}: VersionModalProps) {
  const [versions, setVersions] = useState<ModelVersionListItem[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [diff, setDiff] = useState<CanvasDiff | null>(null);
  const [isDiffLoading, setIsDiffLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [namedOnly, setNamedOnly] = useState(false);
  const [namingVersionId, setNamingVersionId] = useState<string | null>(null);
  const t = useTranslations("builder");

  // Load the full version list when modal opens
  useEffect(() => {
    if (!isOpen) return;
    setIsLoadingList(true);
    api
      .listVersions(documentId, { limit: 200 })
      .then((data) => setVersions(data))
      .catch(() => {})
      .finally(() => setIsLoadingList(false));
  }, [isOpen, documentId]);

  // Compute diff when a version is selected
  const handleSelectVersion = useCallback(
    async (versionId: string) => {
      setSelectedVersionId(versionId);
      setIsDiffLoading(true);
      setDiff(null);
      try {
        const fullVersion = await api.getVersion(documentId, versionId);
        const targetCanvas = fullVersion.canvas_json as { nodes?: unknown[]; edges?: unknown[] };
        const computed = diffCanvasJson(targetCanvas, currentCanvasJson);
        setDiff(computed);
      } catch {
        setDiff(null);
      } finally {
        setIsDiffLoading(false);
      }
    },
    [documentId, currentCanvasJson]
  );

  // Handle successful version naming
  const handleVersionNamed = useCallback(
    (updated: ModelVersion) => {
      setVersions((prev) =>
        prev.map((v) =>
          v.id === updated.id
            ? {
                ...v,
                is_named: updated.is_named,
                version_name: updated.version_name,
              }
            : v
        )
      );
    },
    []
  );

  // Filter versions by search and named filter
  const filteredVersions = versions.filter((v) => {
    if (namedOnly && !v.is_named) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const name = (v.version_name ?? "").toLowerCase();
      const summary = v.change_summary.toLowerCase();
      if (!name.includes(q) && !summary.includes(q)) return false;
    }
    return true;
  });

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
        <DialogContent className="max-w-5xl h-[80vh] flex flex-col gap-0 p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-4 border-b shrink-0">
            <DialogTitle>{t("versions.title")}</DialogTitle>
          </DialogHeader>

          {/* Body: two-panel layout */}
          <div className="flex flex-1 min-h-0">
            {/* Left panel: version list */}
            <div className="w-2/5 border-r flex flex-col">
              <div className="px-4 py-3 border-b space-y-2 shrink-0">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                  <Input
                    placeholder={t("versions.searchPlaceholder")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-8 h-8 text-xs"
                  />
                </div>
                <div className="flex gap-1">
                  <Button
                    variant={namedOnly ? "default" : "outline"}
                    size="sm"
                    className="h-6 px-2 text-xs"
                    onClick={() => setNamedOnly(false)}
                  >
                    {t("versions.all")}
                  </Button>
                  <Button
                    variant={namedOnly ? "outline" : "ghost"}
                    size="sm"
                    className="h-6 px-2 text-xs gap-1"
                    onClick={() => setNamedOnly(true)}
                  >
                    <Filter className="size-3" />
                    {t("versions.namedOnly")}
                  </Button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto">
                {isLoadingList ? (
                  <div className="p-4 space-y-2">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <Skeleton key={i} className="h-14 rounded-md" />
                    ))}
                  </div>
                ) : filteredVersions.length === 0 ? (
                  <div className="p-4 text-xs text-muted-foreground text-center">
                    {versions.length === 0 ? t("versions.noVersionsYet") : t("versions.noMatchingVersions")}
                  </div>
                ) : (
                  <ul className="divide-y">
                    {filteredVersions.map((version) => (
                      <ContextMenu key={version.id}>
                        <ContextMenuTrigger asChild>
                          <li
                            className={`text-xs transition-colors ${
                              selectedVersionId === version.id
                                ? "bg-accent text-accent-foreground"
                                : "hover:bg-muted/50"
                            }`}
                          >
                            <button
                              type="button"
                              onClick={() => handleSelectVersion(version.id)}
                              className="w-full px-4 py-3 text-left cursor-pointer select-none"
                            >
                              <div className="flex items-start gap-2">
                                <div className="mt-0.5 w-4 shrink-0">
                                  {version.is_named && (
                                    <Bookmark className="size-3.5 fill-current text-primary" />
                                  )}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p
                                    className={`truncate leading-tight ${
                                      version.is_named ? "font-semibold" : "font-normal"
                                    }`}
                                  >
                                    {version.is_named && version.version_name
                                      ? version.version_name
                                      : version.change_summary}
                                  </p>
                                  <p className="text-muted-foreground mt-0.5">
                                    {formatRelativeTime(version.created_at)}
                                    <span className="ml-1 opacity-60">#{version.sequence}</span>
                                  </p>
                                </div>
                              </div>
                            </button>
                          </li>
                        </ContextMenuTrigger>
                        <ContextMenuContent>
                          <ContextMenuItem
                            onSelect={() => setNamingVersionId(version.id)}
                          >
                            <Bookmark className="size-4" />
                            {t("versions.nameVersion")}
                          </ContextMenuItem>
                        </ContextMenuContent>
                      </ContextMenu>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {/* Right panel: diff view */}
            <div className="flex-1 flex flex-col min-w-0">
              <div className="flex-1 overflow-y-auto p-5">
                {isDiffLoading ? (
                  <div className="space-y-3">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-16 rounded-md" />
                    <Skeleton className="h-16 rounded-md" />
                    <Skeleton className="h-10 rounded-md" />
                  </div>
                ) : (
                  <DiffPanel diff={diff} />
                )}
              </div>
            </div>
          </div>

          <div className="px-6 py-3 border-t bg-background shrink-0 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {selectedVersionId
                ? t("versions.versionSelected", { sequence: String(filteredVersions.find((v) => v.id === selectedVersionId)?.sequence ?? "?") })
                : t("versions.selectFromList")}
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={onClose}>
                Close
              </Button>
              <Button
                size="sm"
                disabled={!selectedVersionId}
                onClick={() => {
                  if (selectedVersionId) {
                    onRestore(selectedVersionId);
                  }
                }}
              >
                {t("versions.restoreVersion")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <NameVersionDialog
        versionId={namingVersionId}
        documentId={documentId}
        onClose={() => setNamingVersionId(null)}
        onSuccess={handleVersionNamed}
      />
    </>
  );
}
