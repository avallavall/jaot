"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "next-intl";
import { Building2, Plus, Users } from "lucide-react";

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString();
}

export default function WorkspacesPage() {
  const { isOwner } = useAuth();
  const t = useTranslations("workspace.workspaces");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.listWorkspaces();
        setWorkspaces(data.items);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("loadError"));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [t]);

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">{t("title")}</h1>
          <p className="text-muted-foreground">
            {t("subtitle")}
          </p>
        </div>
        {isOwner && (
          <Button asChild>
            <Link href="/workspace/workspaces/new">
              <Plus className="w-4 h-4 mr-2" />
              {t("createWorkspace")}
            </Link>
          </Button>
        )}
      </div>

      {loading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="border rounded-lg p-5 space-y-3 bg-card">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          ))}
        </div>
      )}

      {!loading && workspaces.length === 0 && (
        <div className="text-center py-16 bg-card border-2 border-dashed rounded-xl">
          <Building2 className="w-12 h-12 mx-auto text-muted-foreground/40 mb-4" />
          <h2 className="text-xl font-semibold mb-2">{t("noWorkspacesTitle")}</h2>
          <p className="text-muted-foreground mb-6">
            {isOwner
              ? t("noWorkspacesOwner")
              : t("noWorkspacesUser")}
          </p>
          {isOwner && (
            <Button asChild>
              <Link href="/workspace/workspaces/new">
                <Plus className="w-4 h-4 mr-2" />
                {t("createWorkspace")}
              </Link>
            </Button>
          )}
        </div>
      )}

      {!loading && workspaces.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {workspaces.map((ws) => {
            const usedPercent =
              ws.pool_allocated && ws.pool_allocated > 0 && ws.pool_used != null
                ? Math.min(100, Math.round((ws.pool_used / ws.pool_allocated) * 100))
                : null;

            return (
              <Link
                key={ws.id}
                href={`/workspace/workspaces/${ws.id}`}
                className="border rounded-lg p-5 bg-card hover:border-primary/40 hover:shadow-sm transition-all block"
              >
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-semibold text-lg leading-tight">{ws.name}</h3>
                  {!ws.is_active && (
                    <Badge variant="secondary" className="text-xs ml-2 shrink-0">
                      {t("inactive")}
                    </Badge>
                  )}
                </div>

                {ws.description && (
                  <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
                    {ws.description}
                  </p>
                )}

                <div className="flex items-center gap-1 text-sm text-muted-foreground mb-3">
                  <Users className="w-3.5 h-3.5" />
                  <span>{t("memberCount", { count: ws.member_count })}</span>
                </div>

                {usedPercent !== null && (
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>{t("creditsLabel")}</span>
                      <span>{t("percentUsed", { percent: usedPercent })}</span>
                    </div>
                    <div className="w-full bg-muted rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full ${
                          usedPercent >= 90
                            ? "bg-red-500"
                            : usedPercent >= 70
                            ? "bg-yellow-500"
                            : "bg-green-500"
                        }`}
                        style={{ width: `${usedPercent}%` }}
                      />
                    </div>
                  </div>
                )}

                <p className="text-xs text-muted-foreground mt-3">
                  {t("createdDate", { date: formatDate(ws.created_at) })}
                </p>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
