"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { SolveTrigger } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDialog } from "@/components/ui/dialog-custom";
import { Webhook, Plus, Trash2, ExternalLink, ToggleLeft, ToggleRight, Clock } from "lucide-react";

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

export default function TriggersPage() {
  const router = useRouter();
  const dialog = useDialog();
  const { activeWorkspaceId } = useAuth();
  const canEdit = useWorkspacePermission("editor");
  const roleName = useRoleDisplayName();
  const t = useTranslations("triggers.list");
  const [triggers, setTriggers] = useState<SolveTrigger[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<Record<string, boolean>>({});
  const [scheduledTriggerIds, setScheduledTriggerIds] = useState<Set<string>>(new Set());

  const loadTriggers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.triggers.list(undefined, activeWorkspaceId ?? undefined);
      setTriggers(data);
      // Check which triggers have active schedules
      const scheduleChecks = await Promise.allSettled(
        data.map((trig) => api.schedules.get(trig.id))
      );
      const scheduledIds = new Set<string>();
      scheduleChecks.forEach((result, i) => {
        if (result.status === "fulfilled" && result.value.is_enabled) {
          scheduledIds.add(data[i].id);
        }
      });
      setScheduledTriggerIds(scheduledIds);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId, t]);

  useEffect(() => {
    loadTriggers();
  }, [loadTriggers]);

  const handleToggle = async (trigger: SolveTrigger) => {
    // Optimistic: flip the toggle immediately
    const previousTriggers = triggers;
    setTriggers((prev) =>
      prev.map((tr) =>
        tr.id === trigger.id ? { ...tr, is_enabled: !trigger.is_enabled } : tr
      )
    );
    setToggling((prev) => ({ ...prev, [trigger.id]: true }));
    try {
      const updated = await api.triggers.toggle(trigger.id, !trigger.is_enabled, activeWorkspaceId ?? undefined);
      setTriggers((prev) => prev.map((tr) => (tr.id === trigger.id ? updated : tr)));
      toast.success(t("toggleEnabled", { state: updated.is_enabled ? "enabled" : "disabled" }));
    } catch (err) {
      // Revert on failure
      setTriggers(previousTriggers);
      toast.error(err instanceof Error ? err.message : t("toggleError"));
    } finally {
      setToggling((prev) => ({ ...prev, [trigger.id]: false }));
    }
  };

  const handleDelete = (trigger: SolveTrigger) => {
    dialog.confirmCallback(
      t("deleteConfirm", { name: trigger.name }),
      async () => {
        // Optimistic: remove from list immediately after confirmation
        const previousTriggers = triggers;
        setTriggers((prev) => prev.filter((tr) => tr.id !== trigger.id));
        try {
          await api.triggers.delete(trigger.id, activeWorkspaceId ?? undefined);
          toast.success(t("deleted"));
        } catch (err) {
          // Revert on failure
          setTriggers(previousTriggers);
          toast.error(err instanceof Error ? err.message : t("deleteError"));
        }
      },
      t("deleteTitle")
    );
  };

  const newTriggerHref = activeWorkspaceId
    ? `/triggers/new?workspace_id=${activeWorkspaceId}`
    : "/triggers/new";

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">{t("title")}</h1>
          <p className="text-muted-foreground">
            {t("subtitle")}
          </p>
        </div>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Button asChild={canEdit} disabled={!canEdit}>
                  {canEdit ? (
                    <Link href={newTriggerHref}>
                      <Plus className="w-4 h-4 mr-2" />
                      {t("newTrigger")}
                    </Link>
                  ) : (
                    <>
                      <Plus className="w-4 h-4 mr-2" />
                      {t("newTrigger")}
                    </>
                  )}
                </Button>
              </span>
            </TooltipTrigger>
            {!canEdit && (
              <TooltipContent className="max-w-xs text-center">
                {t("noPermission", { role: roleName })}
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
      </div>

      {loading && (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="border rounded-lg p-4 space-y-2">
              <Skeleton className="h-5 w-1/3" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-1/4" />
            </div>
          ))}
        </div>
      )}

      {!loading && triggers.length === 0 && (
        <div className="text-center py-16 bg-card border-2 border-dashed rounded-xl">
          <Webhook className="w-12 h-12 mx-auto text-muted-foreground/40 mb-4" />
          <h2 className="text-xl font-semibold mb-2">{t("noTriggers")}</h2>
          <p className="text-muted-foreground mb-6">
            {t("noTriggersDescription")}
          </p>
          <Button asChild={canEdit} disabled={!canEdit}>
            {canEdit ? (
              <Link href={newTriggerHref}>
                <Plus className="w-4 h-4 mr-2" />
                {t("createTrigger")}
              </Link>
            ) : (
              <>
                <Plus className="w-4 h-4 mr-2" />
                {t("createTrigger")}
              </>
            )}
          </Button>
        </div>
      )}

      {!loading && triggers.length > 0 && (
        <div className="space-y-3">
          {triggers.map((trigger) => (
            <div
              key={trigger.id}
              className="border rounded-lg p-4 bg-card hover:border-primary/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                {/* Left: info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Link
                      href={activeWorkspaceId ? `/triggers/${trigger.id}?workspace_id=${activeWorkspaceId}` : `/triggers/${trigger.id}`}
                      className="font-semibold hover:text-primary transition-colors truncate"
                    >
                      {trigger.name}
                    </Link>
                    <Badge
                      variant={trigger.is_enabled ? "default" : "secondary"}
                      className="shrink-0"
                    >
                      {trigger.is_enabled ? t("enabled") : t("disabled")}
                    </Badge>
                    {scheduledTriggerIds.has(trigger.id) && (
                      <Badge variant="outline" className="shrink-0 gap-1">
                        <Clock className="w-3 h-3" />
                        {t("scheduled")}
                      </Badge>
                    )}
                  </div>
                  {trigger.description && (
                    <p className="text-sm text-muted-foreground mb-2 line-clamp-1">
                      {trigger.description}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>
                      <span className="font-medium">{trigger.total_runs}</span>{" "}
                      {t("runs", { count: trigger.total_runs })}
                    </span>
                    {trigger.last_fired_at && (
                      <span>{t("lastFired", { date: formatDate(trigger.last_fired_at) })}</span>
                    )}
                    <span>{t("created", { date: formatDate(trigger.created_at) })}</span>
                    <span className="font-mono text-xs">
                      {t("version", { id: trigger.version_id.slice(0, 12) + "..." })}
                    </span>
                  </div>
                </div>

                {/* Right: actions */}
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleToggle(trigger)}
                    disabled={toggling[trigger.id] || !canEdit}
                    title={trigger.is_enabled ? t("disableTrigger") : t("enableTrigger")}
                    className="text-muted-foreground"
                  >
                    {trigger.is_enabled ? (
                      <ToggleRight className="w-5 h-5 text-primary" />
                    ) : (
                      <ToggleLeft className="w-5 h-5" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(activeWorkspaceId ? `/triggers/${trigger.id}?workspace_id=${activeWorkspaceId}` : `/triggers/${trigger.id}`)}
                    title={t("viewDetails")}
                  >
                    <ExternalLink className="w-4 h-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(trigger)}
                    disabled={!canEdit}
                    title={t("deleteTrigger")}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <dialog.DialogComponent />
    </div>
  );
}
