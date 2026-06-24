"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import {
  Store, Wrench, Coins, ClipboardList, Building2,
  Bell, Webhook, Activity,
} from "lucide-react";
import type { ModelExecution, SolveTrigger, UserInfo } from "@/lib/types";

interface DashboardStats {
  activeTriggers: number;
  unreadNotifications: number;
  recentExecutions: ModelExecution[];
}

export default function DashboardPage() {
  const router = useRouter();
  const { logout } = useAuth();
  const t = useTranslations("workspace");
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadDashboard() {
      try {
        const [info, executions, triggers, notifications] = await Promise.all([
          api.getMe(),
          api.getAllExecutions({ page_size: "5" }).catch(() => ({ items: [] as ModelExecution[] })),
          api.triggers.list().catch(() => [] as SolveTrigger[]),
          api.getUnreadCount().catch(() => ({ unread_count: 0 })),
        ]);

        setUserInfo(info);
        setStats({
          activeTriggers: triggers.length,
          unreadNotifications: notifications.unread_count,
          recentExecutions: executions.items,
        });
      } catch {
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }

    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3"></div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-muted rounded"></div>
            ))}
          </div>
          <div className="h-64 bg-muted rounded"></div>
        </div>
      </div>
    );
  }

  if (!userInfo) {
    return null;
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-foreground">{t("title")}</h1>
          <p className="text-muted-foreground mt-1">
            {userInfo.organization_name} · <span className="capitalize">{userInfo.plan}</span>
          </p>
        </div>
        <Button variant="outline" onClick={logout}>
          {t("dashboard.logOut")}
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <Link href="/workspace/credits" className="bg-card border border-border rounded-lg p-4 hover:bg-muted/50 transition-colors">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <Coins className="w-4 h-4" />
            <span className="text-sm">{t("dashboard.credits")}</span>
          </div>
          <div className="text-2xl font-bold text-primary">{userInfo.credits_balance?.toLocaleString() ?? 0}</div>
        </Link>

        <Link href="/triggers" className="bg-card border border-border rounded-lg p-4 hover:bg-muted/50 transition-colors">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <Webhook className="w-4 h-4" />
            <span className="text-sm">{t("dashboard.activeTriggers")}</span>
          </div>
          <div className="text-2xl font-bold">{stats?.activeTriggers ?? 0}</div>
        </Link>

        <div className="bg-card border border-border rounded-lg p-4">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <Bell className="w-4 h-4" />
            <span className="text-sm">{t("dashboard.unreadNotifications")}</span>
          </div>
          <div className="text-2xl font-bold">{stats?.unreadNotifications ?? 0}</div>
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{t("dashboard.recentExecutions")}</h2>
          <Link href="/solve/executions">
            <Button variant="ghost" size="sm">{t("dashboard.viewAll")}</Button>
          </Link>
        </div>
        {stats?.recentExecutions && stats.recentExecutions.length > 0 ? (
          <div className="space-y-2">
            {stats.recentExecutions.map((exec) => (
              <Link
                key={exec.id}
                href={`/solve/executions/${exec.id}`}
                className="flex items-center justify-between p-3 rounded-md hover:bg-muted/50 transition-colors border border-border"
              >
                <div className="flex items-center gap-3">
                  <Activity className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm font-medium truncate max-w-[200px]">{exec.id}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    exec.status === "completed" ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" :
                    exec.status === "failed" ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400" :
                    exec.status === "running" ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400" :
                    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                  }`}>
                    {exec.status}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(exec.created_at).toLocaleDateString()}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-4">
            {t("dashboard.noRecentExecutions")}
          </p>
        )}
      </div>

      <div className="bg-card border border-border rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">{t("dashboard.quickLinks")}</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Link href="/marketplace" className="p-4 border rounded-lg hover:bg-muted/50 transition-colors text-center">
            <div className="flex justify-center mb-2"><Store className="w-6 h-6 text-primary" /></div>
            <div className="text-sm font-medium">{t("dashboard.modelCatalog")}</div>
          </Link>
          <Link href="/solve/executions" className="p-4 border rounded-lg hover:bg-muted/50 transition-colors text-center">
            <div className="flex justify-center mb-2"><ClipboardList className="w-6 h-6 text-primary" /></div>
            <div className="text-sm font-medium">{t("dashboard.executions")}</div>
          </Link>
          <Link href="/workspace/profile" className="p-4 border rounded-lg hover:bg-muted/50 transition-colors text-center">
            <div className="flex justify-center mb-2"><Building2 className="w-6 h-6 text-primary" /></div>
            <div className="text-sm font-medium">{t("dashboard.organizationProfile")}</div>
          </Link>
          {userInfo.is_admin && (
            <Link href="/admin" className="p-4 border rounded-lg hover:bg-muted/50 transition-colors text-center">
              <div className="flex justify-center mb-2"><Wrench className="w-6 h-6 text-primary" /></div>
              <div className="text-sm font-medium">{t("dashboard.adminPanel")}</div>
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
