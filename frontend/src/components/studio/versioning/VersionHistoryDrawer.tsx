"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { GitCompare, RotateCcw, Sparkles } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useExplanationStream } from "@/hooks/useExplanationStream";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { ByokHint } from "@/components/llm/ByokHint";
import type { Conversation } from "@/lib/llm-types";
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
  const tBuilder = useTranslations("builder");
  const { activeWorkspaceId } = useAuth();
  const ws = activeWorkspaceId ?? undefined;

  const [versions, setVersions] = useState<ProjectVersionSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [diff, setDiff] = useState<ProjectVersionDiff | null>(null);
  /** The [from, to] version ids of the current diff — the explain-diff payload. */
  const [comparePair, setComparePair] = useState<[string, string] | null>(null);

  const explain = useExplanationStream();
  const conversationIdRef = useRef<string | null>(null);
  const [explainSetupFailed, setExplainSetupFailed] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    explain.reset();
    setComparePair(null);
    setExplainSetupFailed(false);
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
    // explain is stable across renders; reset only needs to fire on open/refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, projectId, ws, refreshKey]);

  const toggleSelect = useCallback(
    (id: string) => {
      setDiff(null);
      setComparePair(null);
      explain.reset();
      setSelected((prev) => {
        if (prev.includes(id)) return prev.filter((x) => x !== id);
        // keep the two most-recently picked
        return [...prev, id].slice(-2);
      });
    },
    [explain]
  );

  const handleCompare = useCallback(async () => {
    if (selected.length !== 2) return;
    // Order oldest → newest by sequence so the diff reads "from → to".
    const seqOf = (id: string) => versions.find((v) => v.id === id)?.sequence ?? 0;
    const [a, b] = [...selected].sort((x, y) => seqOf(x) - seqOf(y));
    explain.reset();
    setExplainSetupFailed(false);
    try {
      setDiff(await api.diffProjectVersions(projectId, a, b, ws));
      setComparePair([a, b]);
    } catch {
      /* ignore */
    }
  }, [selected, versions, projectId, ws, explain]);

  const runExplainDiff = useCallback(async () => {
    if (!comparePair) return;
    setExplainSetupFailed(false);
    try {
      if (!conversationIdRef.current) {
        const conv = await api.request<Conversation>("/api/v2/llm/conversations", {
          method: "POST",
          body: JSON.stringify({}),
        });
        conversationIdRef.current = conv.id;
      }
      await explain.explain(
        `/api/v2/llm/conversations/${conversationIdRef.current}/explain-diff`,
        { project_id: projectId, from_version_id: comparePair[0], to_version_id: comparePair[1] }
      );
    } catch {
      setExplainSetupFailed(true);
    }
  }, [comparePair, projectId, explain]);

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

        {comparePair && (
          <div className="border-t pt-3 space-y-2">
            {!explain.streaming && (
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={runExplainDiff}
                data-testid="studio-explain-diff-run"
              >
                <Sparkles className="h-3.5 w-3.5" />
                {explain.text ? t("explainRegenerate") : t("explainDiffButton")}
              </Button>
            )}
            {explain.streaming && !explain.text && (
              <p className="text-xs text-muted-foreground animate-pulse">
                {t("explainDiffThinking")}
              </p>
            )}
            {explain.text && (
              <div className="prose prose-sm dark:prose-invert max-w-none text-foreground max-h-48 overflow-y-auto">
                <Markdown remarkPlugins={[remarkGfm]}>{explain.text}</Markdown>
              </div>
            )}
            {(explainSetupFailed || explain.errorCode !== null) && (
              <p className="text-xs text-destructive">
                {explain.errorCode
                  ? tBuilder(resolveErrorKey(explain.errorCode))
                  : tBuilder(resolveErrorKey("service_unavailable"))}
                {explain.requestId && (
                  <span className="text-muted-foreground">
                    {" "}
                    {t("explainRef", { requestId: explain.requestId })}
                  </span>
                )}
              </p>
            )}
            {explain.text && <ByokHint />}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
