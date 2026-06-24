"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { AuditLogEntry, WorkspaceMember } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Building2, ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import Link from "next/link";
import { ACTION_LABELS, getActionMeta } from "@/lib/audit-labels";

function formatTimestamp(dateStr: string, t: (key: string, values?: Record<string, string | number | Date>) => string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return t("timeJustNow");
  if (diffMins < 60) return t("timeMinutesAgo", { count: diffMins });
  if (diffHours < 24) return t("timeHoursAgo", { count: diffHours });
  if (diffDays === 1) return t("timeYesterday");
  if (diffDays < 7) return t("timeDaysAgo", { count: diffDays });
  return date.toLocaleString();
}

interface ExpandedRowProps {
  entry: AuditLogEntry;
  t: (key: string) => string;
}

function ExpandedRow({ entry, t }: ExpandedRowProps) {
  return (
    <div className="px-4 py-3 bg-muted/30 border-t space-y-3 text-sm">
      {entry.before_state && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">{t("expandedBefore")}</p>
          <pre className="bg-background border rounded p-2 text-xs overflow-auto max-h-40">
            {JSON.stringify(entry.before_state, null, 2)}
          </pre>
        </div>
      )}
      {entry.after_state && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">{t("expandedAfter")}</p>
          <pre className="bg-background border rounded p-2 text-xs overflow-auto max-h-40">
            {JSON.stringify(entry.after_state, null, 2)}
          </pre>
        </div>
      )}
      {entry.metadata && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">{t("expandedMetadata")}</p>
          <pre className="bg-background border rounded p-2 text-xs overflow-auto max-h-40">
            {JSON.stringify(entry.metadata, null, 2)}
          </pre>
        </div>
      )}
      {!entry.before_state && !entry.after_state && !entry.metadata && (
        <p className="text-muted-foreground text-xs">{t("noDetails")}</p>
      )}
    </div>
  );
}

export default function AuditLogPage() {
  const router = useRouter();
  const { activeWorkspaceId, isOwner } = useAuth();
  const isAdmin = usePermission("admin");
  const roleName = useRoleDisplayName();
  const t = useTranslations("workspace.audit");
  const tc = useTranslations("common");

  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Filters
  const [actionFilter, setActionFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const limit = 20;
  const totalPages = Math.ceil(total / limit);

  useEffect(() => {
    if (!isAdmin && activeWorkspaceId) {
      toast.error(t("adminRequired", { role: roleName }));
      router.push("/workspace");
    }
  }, [isAdmin, activeWorkspaceId, router, t, roleName]);

  useEffect(() => {
    if (!activeWorkspaceId) return;
    api.listMembers(activeWorkspaceId).then(setMembers).catch(() => {});
  }, [activeWorkspaceId]);

  const loadLogs = useCallback(async () => {
    if (!activeWorkspaceId || !isAdmin) return;
    setLoading(true);
    try {
      const data = await api.listAuditLogs(activeWorkspaceId, {
        action: actionFilter || undefined,
        actor_id: actorFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page,
        limit,
      });
      setEntries(data.items);
      setTotal(data.total);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId, isAdmin, actionFilter, actorFilter, dateFrom, dateTo, page, t]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const toggleRow = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleFilterChange = () => {
    setPage(1);
  };

  if (!activeWorkspaceId) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-5xl">
        <h1 className="text-3xl font-bold mb-2">{t("title")}</h1>
        <div className="text-center py-16 bg-card border-2 border-dashed rounded-xl">
          <Building2 className="w-12 h-12 mx-auto text-muted-foreground/40 mb-4" />
          <h2 className="text-xl font-semibold mb-2">{t("noWorkspace")}</h2>
          <p className="text-muted-foreground mb-6">{t("noWorkspaceDescription")}</p>
          <div className="flex items-center justify-center gap-3">
            {isOwner && (
              <Button asChild>
                <Link href="/workspace/workspaces/new">{t("createWorkspace")}</Link>
              </Button>
            )}
            <Button variant={isOwner ? "outline" : "default"} asChild>
              <Link href="/workspace/workspaces">{t("browseWorkspaces")}</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="flex items-center gap-3 mb-6">
        <ScrollText className="w-6 h-6 text-primary" />
        <div>
          <h1 className="text-3xl font-bold">{t("title")}</h1>
          <p className="text-muted-foreground">{t("subtitle")}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6 p-4 border rounded-lg bg-card">
        <Select
          value={actionFilter || "__all"}
          onValueChange={(v) => {
            setActionFilter(v === "__all" ? "" : v);
            handleFilterChange();
          }}
        >
          <SelectTrigger>
            <SelectValue placeholder={t("allActions")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all">{t("allActions")}</SelectItem>
            {Object.keys(ACTION_LABELS).map((a) => (
              <SelectItem key={a} value={a}>
                {ACTION_LABELS[a].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={actorFilter || "__all"}
          onValueChange={(v) => {
            setActorFilter(v === "__all" ? "" : v);
            handleFilterChange();
          }}
        >
          <SelectTrigger>
            <SelectValue placeholder={t("allActors")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all">{t("allActors")}</SelectItem>
            {members.map((m) => (
              <SelectItem key={m.user_id} value={m.user_id}>
                {m.user_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="space-y-1">
          <Input
            type="date"
            placeholder={t("fromDate")}
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); handleFilterChange(); }}
            className="text-xs"
          />
        </div>

        <div className="space-y-1">
          <Input
            type="date"
            placeholder={t("toDate")}
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); handleFilterChange(); }}
            className="text-xs"
          />
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="border rounded-lg p-3 flex items-center gap-4">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
      )}

      {!loading && entries.length === 0 && (
        <div className="text-center py-12 text-muted-foreground">
          <ScrollText className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p>{t("noEntries")}</p>
        </div>
      )}

      {!loading && entries.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="w-6 px-2" />
                <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("tableHeaders.actor")}</th>
                <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("tableHeaders.action")}</th>
                <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("tableHeaders.target")}</th>
                <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("tableHeaders.time")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const isExpanded = expandedIds.has(entry.id);
                const actionMeta = getActionMeta(entry.action);
                return (
                  <>
                    <tr
                      key={entry.id}
                      className="border-b last:border-0 hover:bg-muted/20 cursor-pointer"
                      onClick={() => toggleRow(entry.id)}
                    >
                      <td className="px-2 py-3 text-center text-muted-foreground">
                        {isExpanded ? (
                          <ChevronDown className="w-3 h-3 mx-auto" />
                        ) : (
                          <ChevronRight className="w-3 h-3 mx-auto" />
                        )}
                      </td>
                      <td className="px-4 py-3 font-medium">{entry.actor_name}</td>
                      <td className="px-4 py-3">
                        <Badge className={`${actionMeta.color} border-0 text-xs`}>
                          {actionMeta.label}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {entry.target_name ?? entry.target_type ?? "\u2014"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                        {formatTimestamp(entry.created_at, t)}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${entry.id}-expanded`} className="border-b last:border-0">
                        <td colSpan={5} className="p-0">
                          <ExpandedRow entry={entry} t={t} />
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-muted-foreground">
            {t("totalEntries", { count: total })}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              {tc("previous")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {t("pageOf", { page, totalPages })}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
            >
              {tc("next")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
