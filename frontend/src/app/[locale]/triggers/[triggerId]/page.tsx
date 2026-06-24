"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { SolveTrigger, OverrideField } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import {
  useWorkspaceScopeGuard,
  WorkspaceSwitchPrompt,
} from "@/components/workspace/WorkspaceSwitchPrompt";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDialog } from "@/components/ui/dialog-custom";
import { CodeSnippets } from "@/components/triggers/CodeSnippets";
import { RunHistoryTable } from "@/components/triggers/RunHistoryTable";
import { ScheduleTab } from "@/components/triggers/ScheduleTab";
import {
  ChevronLeft,
  Clock,
  Copy,
  Check,
  ToggleLeft,
  ToggleRight,
  Trash2,
  ExternalLink,
} from "lucide-react";

function CopyButton({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const t = useTranslations("triggers.detail");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(label ? t("copiedLabel", { label }) : t("copiedClipboard"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("copyError"));
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center justify-center h-7 w-7 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
      title={t("copyLabel", { label: label ?? "" })}
    >
      {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

function TriggerDetailPageInner() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlWorkspaceId = searchParams.get("workspace_id");
  const dialog = useDialog();
  const triggerId = params.triggerId as string;
  const t = useTranslations("triggers.detail");

  const { activeWorkspaceId } = useAuth();
  const canEdit = useWorkspacePermission("editor");
  const roleName = useRoleDisplayName();

  // Workspace scope guard -- prompts if URL workspace differs from active
  const { showPrompt, targetWorkspaceName, handleAccept, handleDecline } =
    useWorkspaceScopeGuard(urlWorkspaceId);

  const [trigger, setTrigger] = useState<SolveTrigger | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTrigger = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.triggers.get(triggerId, activeWorkspaceId ?? undefined);
      setTrigger(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [triggerId, activeWorkspaceId, t]);

  useEffect(() => {
    loadTrigger();
  }, [loadTrigger]);

  const handleToggle = async () => {
    if (!trigger) return;
    setToggling(true);
    try {
      const updated = await api.triggers.toggle(trigger.id, !trigger.is_enabled, activeWorkspaceId ?? undefined);
      setTrigger(updated);
      toast.success(t("toggleEnabled", { state: updated.is_enabled ? "enabled" : "disabled" }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toggleError"));
    } finally {
      setToggling(false);
    }
  };

  const handleDelete = () => {
    if (!trigger) return;
    dialog.confirmCallback(
      t("deleteConfirm", { name: trigger.name }),
      async () => {
        try {
          await api.triggers.delete(trigger.id, activeWorkspaceId ?? undefined);
          toast.success(t("deleted"));
          router.push("/triggers");
        } catch (err) {
          toast.error(err instanceof Error ? err.message : t("deleteError"));
        }
      },
      t("deleteTitle")
    );
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-4xl">
        <Skeleton className="h-4 w-32 mb-6" />
        <Skeleton className="h-8 w-64 mb-2" />
        <Skeleton className="h-4 w-48 mb-8" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (error || !trigger) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-4xl">
        <Link
          href="/triggers"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-6"
        >
          <ChevronLeft className="w-4 h-4" />
          {t("backToTriggers")}
        </Link>
        <div className="bg-destructive/10 text-destructive rounded-lg p-4">
          {error ?? t("notFound")}
        </div>
      </div>
    );
  }

  const overrideSchema: OverrideField[] | null = trigger.override_schema;

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <Link
        href="/triggers"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6"
      >
        <ChevronLeft className="w-4 h-4" />
        {t("backToTriggers")}
      </Link>

      <div className="flex items-start justify-between mb-6 gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap mb-1">
            <h1 className="text-2xl font-bold truncate">{trigger.name}</h1>
            <Badge variant={trigger.is_enabled ? "default" : "secondary"}>
              {trigger.is_enabled ? t("enable") + "d" : t("disable") + "d"}
            </Badge>
          </div>
          {trigger.description && (
            <p className="text-muted-foreground">{trigger.description}</p>
          )}
        </div>
        <TooltipProvider>
          <div className="flex items-center gap-2 shrink-0">
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleToggle}
                    disabled={toggling || !canEdit}
                    className="gap-2"
                  >
                    {trigger.is_enabled ? (
                      <>
                        <ToggleRight className="w-4 h-4 text-primary" />
                        {t("disable")}
                      </>
                    ) : (
                      <>
                        <ToggleLeft className="w-4 h-4" />
                        {t("enable")}
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
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleDelete}
                    disabled={!canEdit}
                    className="gap-2 text-destructive hover:text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="w-4 h-4" />
                    {t("deleteTitle")}
                  </Button>
                </span>
              </TooltipTrigger>
              {!canEdit && (
                <TooltipContent className="max-w-xs text-center">
                  {t("noPermission", { role: roleName })}
                </TooltipContent>
              )}
            </Tooltip>
          </div>
        </TooltipProvider>
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="mb-6">
          <TabsTrigger value="overview">{t("overviewTab")}</TabsTrigger>
          <TabsTrigger value="runs">{t("runHistoryTab")}</TabsTrigger>
          <TabsTrigger value="schedule">
            <Clock className="w-4 h-4 mr-1.5" />
            {t("scheduleTab")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="space-y-6">
            <div className="border rounded-lg overflow-hidden">
              <div className="bg-muted/50 px-4 py-3 border-b">
                <h2 className="font-semibold text-sm">{t("configTitle")}</h2>
              </div>
              <div className="divide-y">
                <div className="flex items-start gap-4 px-4 py-3">
                  <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("model")}</div>
                  <div className="text-sm font-mono break-all flex-1">
                    {trigger.document_id}
                  </div>
                </div>
                <div className="flex items-start gap-4 px-4 py-3">
                  <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("pinnedVersion")}</div>
                  <div className="text-sm font-mono break-all flex-1">
                    {trigger.version_id}
                  </div>
                </div>
                <div className="flex items-start gap-4 px-4 py-3">
                  <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("webhookUrl")}</div>
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="text-sm font-mono break-all truncate">{trigger.webhook_url}</span>
                    <CopyButton value={trigger.webhook_url} label={t("webhookUrl")} />
                    <a
                      href={trigger.webhook_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </div>
                </div>
                <div className="flex items-start gap-4 px-4 py-3">
                  <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("triggerSecret")}</div>
                  <div className="text-sm text-muted-foreground">
                    <code className="bg-muted px-1 rounded font-mono">{trigger.trigger_secret_prefix}...</code>
                    <span className="ml-2 text-xs">{t("secretShownOnce")}</span>
                  </div>
                </div>
                <div className="flex items-start gap-4 px-4 py-3">
                  <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("totalRuns")}</div>
                  <div className="text-sm">{trigger.total_runs}</div>
                </div>
                {trigger.last_fired_at && (
                  <div className="flex items-start gap-4 px-4 py-3">
                    <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("lastFired")}</div>
                    <div className="text-sm">{new Date(trigger.last_fired_at).toLocaleString()}</div>
                  </div>
                )}
                <div className="flex items-start gap-4 px-4 py-3">
                  <div className="w-40 shrink-0 text-sm text-muted-foreground">{t("createdAt")}</div>
                  <div className="text-sm">{new Date(trigger.created_at).toLocaleString()}</div>
                </div>
              </div>
            </div>

            <div className="border rounded-lg overflow-hidden">
              <div className="bg-muted/50 px-4 py-3 border-b">
                <h2 className="font-semibold text-sm">{t("overrideSchemaTitle")}</h2>
              </div>
              <div className="px-4 py-3">
                {!overrideSchema || overrideSchema.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {overrideSchema === null
                      ? t("openSchema")
                      : t("noOverrides")}
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b">
                          <th className="text-left pb-2 text-xs font-medium text-muted-foreground">{t("schemaName")}</th>
                          <th className="text-left pb-2 text-xs font-medium text-muted-foreground">{t("schemaType")}</th>
                          <th className="text-left pb-2 text-xs font-medium text-muted-foreground">{t("schemaFieldPath")}</th>
                          <th className="text-left pb-2 text-xs font-medium text-muted-foreground">{t("schemaDefault")}</th>
                          <th className="text-left pb-2 text-xs font-medium text-muted-foreground">{t("schemaRequired")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {overrideSchema.map((field, i) => (
                          <tr key={i} className="border-b last:border-0">
                            <td className="py-2 font-medium">{field.name}</td>
                            <td className="py-2 text-muted-foreground">{field.type}</td>
                            <td className="py-2 font-mono text-xs">{field.model_field_path}</td>
                            <td className="py-2 text-muted-foreground">
                              {field.default !== undefined ? String(field.default) : "\u2014"}
                            </td>
                            <td className="py-2">
                              {field.required ? (
                                <Badge variant="default" className="text-xs">{t("schemaRequired")}</Badge>
                              ) : (
                                <span className="text-muted-foreground text-xs">No</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>

            <div className="border rounded-lg overflow-hidden">
              <div className="bg-muted/50 px-4 py-3 border-b">
                <h2 className="font-semibold text-sm">{t("integration")}</h2>
              </div>
              <div className="p-4">
                <CodeSnippets
                  triggerId={trigger.id}
                  triggerSecretPrefix={trigger.trigger_secret_prefix}
                  overrideSchema={trigger.override_schema}
                  webhookUrl={trigger.webhook_url}
                />
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="runs">
          <RunHistoryTable triggerId={triggerId} />
        </TabsContent>

        <TabsContent value="schedule">
          <ScheduleTab triggerId={triggerId} />
        </TabsContent>
      </Tabs>

      <dialog.DialogComponent />
      <WorkspaceSwitchPrompt
        open={showPrompt}
        workspaceName={targetWorkspaceName}
        onAccept={handleAccept}
        onDecline={handleDecline}
      />
    </div>
  );
}

export default function TriggerDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto px-4 py-8 max-w-4xl">
          <Skeleton className="h-4 w-32 mb-6" />
          <Skeleton className="h-8 w-64 mb-2" />
          <Skeleton className="h-4 w-48 mb-8" />
          <Skeleton className="h-48 w-full" />
        </div>
      }
    >
      <TriggerDetailPageInner />
    </Suspense>
  );
}
