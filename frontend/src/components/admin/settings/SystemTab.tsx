"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { AdminStats } from "@/lib/types";
import { useTranslations } from "next-intl";

export interface HealthData {
  status: string;
  version: string;
  solver: string;
  system: {
    cpu_percent: number;
    memory_percent: number;
    memory_available_mb: number;
    disk_usage_percent: number;
  };
  uptime_seconds: number;
  python_version: string;
}

interface SystemTabProps {
  health: HealthData | null;
  stats: AdminStats | null;
  loading: boolean;
}

function ResourceMeter({
  label,
  value,
  loading,
  subtitle,
}: {
  label: string;
  value: number | null;
  loading: boolean;
  subtitle?: string;
}) {
  const pct = value ?? 0;
  const color = pct > 80 ? "bg-destructive" : pct > 60 ? "bg-amber-500" : "bg-primary";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        {loading ? (
          <Skeleton className="h-4 w-12" />
        ) : (
          <span className="font-medium">{pct.toFixed(1)}%</span>
        )}
      </div>
      <div className="w-full bg-muted rounded-full h-2">
        {!loading && (
          <div
            className={`h-2 rounded-full transition-all ${color}`}
            style={{ width: `${pct}%` }}
          />
        )}
        {loading && <Skeleton className="h-2 w-full" />}
      </div>
      {subtitle && !loading && <p className="text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

export function SystemTab({ health, stats, loading }: SystemTabProps) {
  const t = useTranslations("admin.settings");

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="text-lg font-serif flex items-center gap-2">
          {t("systemInfo")}
          {loading ? (
            <Skeleton className="h-5 w-16" />
          ) : (
            <Badge
              variant={health?.status === "ok" ? "default" : "destructive"}
              className="text-xs"
            >
              {health?.status === "ok" ? t("healthy") : t("degraded")}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-sm text-muted-foreground">{t("platformVersion")}</p>
            {loading ? (
              <Skeleton className="h-5 w-24 mt-1" />
            ) : (
              <p className="font-medium">JAOT v{health?.version ?? "2.0.0"}</p>
            )}
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t("solver")}</p>
            {loading ? (
              <Skeleton className="h-5 w-32 mt-1" />
            ) : (
              <p className="font-medium">{health?.solver ?? "SCIP"}</p>
            )}
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t("python")}</p>
            {loading ? (
              <Skeleton className="h-5 w-16 mt-1" />
            ) : (
              <p className="font-medium">{health?.python_version ?? "\u2014"}</p>
            )}
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t("uptime")}</p>
            {loading ? (
              <Skeleton className="h-5 w-20 mt-1" />
            ) : (
              <p className="font-medium">
                {health ? formatUptime(health.uptime_seconds) : "\u2014"}
              </p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-border">
          <ResourceMeter
            label={t("cpuUsage")}
            value={health?.system.cpu_percent ?? null}
            loading={loading}
          />
          <ResourceMeter
            label={t("memoryUsage")}
            value={health?.system.memory_percent ?? null}
            loading={loading}
            subtitle={
              health
                ? t("memoryFree", { amount: health.system.memory_available_mb.toFixed(0) })
                : undefined
            }
          />
          <ResourceMeter
            label={t("diskUsage")}
            value={health?.system.disk_usage_percent ?? null}
            loading={loading}
          />
        </div>

        {!loading && stats && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 pt-2 border-t border-border text-center">
            <div>
              <p className="text-2xl font-bold text-foreground">{stats.organizations.total}</p>
              <p className="text-xs text-muted-foreground">{t("organizations")}</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-foreground">{stats.users.total}</p>
              <p className="text-xs text-muted-foreground">{t("users")}</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-foreground">{stats.users.active}</p>
              <p className="text-xs text-muted-foreground">{t("activeUsers")}</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-foreground">{stats.models.catalog_total}</p>
              <p className="text-xs text-muted-foreground">{t("catalogModels")}</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-foreground">
                {stats.credits.total_balance.toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground">{t("creditBalance")}</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
