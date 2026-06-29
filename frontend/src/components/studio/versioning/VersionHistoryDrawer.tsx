"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { GitCompare, RotateCcw } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import type { ProjectVersionSummary, ProjectVersionDiff } from "@/lib/types";

interface VersionHistoryDrawerProps {
  projectId: string;
  isOpen: boolean;
  /** Bumped on commit/restore so the list refetches. */
  refreshKey: number;
  onClose: () => void;
  onRestore: (versionId: string) => void;
}

/**
 * Full version history for a ModelProject: the committed timeline (`/projects/{id}/
 * versions`), restore, and a structural diff between any two versions
 * (`/versions/{a}/diff/{b}`). Versions are immutable; restoring checks one out into
 * the draft.
 */
export function VersionHistoryDrawer({
  projectId,
  isOpen,
  refreshKey,
  onClose,
  onRestore,
}: VersionHistoryDrawerProps) {
  const t = useTranslations("studio");
  const { activeWorkspaceId } = useAuth();
  const ws = activeWorkspaceId ?? undefined;

  const [versions, setVersions] = useState<ProjectVersionSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [diff, setDiff] = useState<ProjectVersionDiff | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    api
      .listProjectVersions(projectId, { limit: 100 }, ws)
      .then((list) => {
        if (cancelled) return;
        setVersions(list);
        setSelected([]);
        setDiff(null);
      })
      .catch(() => {
        /* non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, projectId, ws, refreshKey]);

  const toggleSelect = useCallback((id: string) => {
    setDiff(null);
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      // keep the two most-recently picked
      return [...prev, id].slice(-2);
    });
  }, []);

  const handleCompare = useCallback(async () => {
    if (selected.length !== 2) return;
    // Order oldest → newest by sequence so the diff reads "from → to".
    const seqOf = (id: string) => versions.find((v) => v.id === id)?.sequence ?? 0;
    const [a, b] = [...selected].sort((x, y) => seqOf(x) - seqOf(y));
    try {
      setDiff(await api.diffProjectVersions(projectId, a, b, ws));
    } catch {
      /* ignore */
    }
  }, [selected, versions, projectId, ws]);

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("versionHistoryTitle")}</DialogTitle>
        </DialogHeader>

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{t("versionCompareHint")}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={selected.length !== 2}
            onClick={handleCompare}
          >
            <GitCompare className="h-3.5 w-3.5 mr-1" />
            {t("versionCompare")}
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
          {versions.length === 0 && (
            <p className="text-sm text-muted-foreground py-6 text-center">
              {t("versionEmpty")}
            </p>
          )}
          {versions.map((v) => {
            const isSelected = selected.includes(v.id);
            return (
              <div
                key={v.id}
                className={`flex items-center gap-3 rounded-md border p-2.5 text-sm ${
                  isSelected ? "border-primary bg-primary/5" : ""
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggleSelect(v.id)}
                  className="flex-1 text-left min-w-0"
                >
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium">
                      v{v.sequence}
                    </span>
                    <span className="truncate font-medium">{v.commit_summary}</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {v.problem_class ? `${v.problem_class} · ` : ""}
                    {new Date(v.created_at).toLocaleString()}
                  </div>
                </button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRestore(v.id)}
                  title={t("versionRestore")}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })}
        </div>

        {diff && (
          <div className="border-t pt-3 max-h-40 overflow-y-auto">
            <p className="text-xs font-medium mb-1">{t("versionDiffTitle")}</p>
            {diff.entries.length === 0 && !diff.objective_changed ? (
              <p className="text-xs text-muted-foreground">{t("versionDiffNone")}</p>
            ) : (
              <ul className="space-y-0.5 text-xs">
                {diff.objective_changed && (
                  <li className="text-amber-600">~ {t("versionDiffObjective")}</li>
                )}
                {diff.entries.map((e, i) => (
                  <li
                    key={`${e.kind}-${e.name}-${i}`}
                    className={
                      e.change === "added"
                        ? "text-emerald-600"
                        : e.change === "removed"
                          ? "text-destructive"
                          : "text-amber-600"
                    }
                  >
                    {e.change === "added" ? "+" : e.change === "removed" ? "−" : "~"} {e.kind}{" "}
                    <span className="font-medium">{e.name}</span>
                    {e.detail ? ` — ${e.detail}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
