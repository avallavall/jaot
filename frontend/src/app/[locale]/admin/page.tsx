"use client";

import { type ReactNode, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import type { AdminStats } from "@/lib/types";
import {
  AlertTriangle,
  Building2,
  CheckCircle,
  Coins,
  KeyRound,
  Users,
} from "lucide-react";

export default function AdminDashboard() {
  const t = useTranslations("admin.dashboard");
  const tc = useTranslations("common");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [maintenanceLoading, setMaintenanceLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    loadStats();
    loadMaintenanceStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadStats = async () => {
    try {
      const data = await api.admin.getStats();
      setStats(data);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const loadMaintenanceStatus = async () => {
    try {
      const data = await api.admin.getSettingsValues("system");
      const value = data.settings?.MAINTENANCE_MODE?.value;
      setMaintenanceMode(value === "true");
    } catch {
      // Silently fail — maintenance card will show as OFF
    } finally {
      setMaintenanceLoading(false);
    }
  };

  const toggleMaintenance = async () => {
    const newValue = !maintenanceMode;
    setToggling(true);
    try {
      await api.admin.updateSettings({ MAINTENANCE_MODE: newValue ? "true" : "false" });
      setMaintenanceMode(newValue);
      const status = newValue ? t("enabled") : t("disabled");
      toast.success(t("maintenanceToggled", { status }));
    } catch (err) {
      toast.error(getErrorMessage(err, t("failedMaintenanceToggle")));
    } finally {
      setToggling(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">{tc("loading")}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-destructive/10 border border-destructive/20 text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">
          {t("subtitle")}
        </p>
      </div>

      <Card className={maintenanceMode
        ? "border-amber-500 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-600"
        : "border-border"
      }>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                {maintenanceMode
                  ? <AlertTriangle className="w-6 h-6 text-amber-500" />
                  : <CheckCircle className="w-6 h-6 text-emerald-500" />}
                <div>
                  <h3 className="text-lg font-semibold text-foreground">
                    {t("maintenanceMode")}
                  </h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    {t("maintenanceDescription")}
                  </p>
                </div>
              </div>
              <div className="mt-3 ml-11">
                <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${
                  maintenanceMode
                    ? "text-amber-700 dark:text-amber-400"
                    : "text-emerald-700 dark:text-emerald-400"
                }`}>
                  <span className={`inline-block w-2 h-2 rounded-full ${
                    maintenanceMode ? "bg-amber-500" : "bg-emerald-500"
                  }`} />
                  {maintenanceMode ? t("maintenanceActive") : t("maintenanceInactive")}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <div
                    role="button"
                    tabIndex={0}
                    className="inline-flex items-center gap-2 cursor-pointer"
                  >
                    <span className="text-sm text-muted-foreground mr-1">
                      {maintenanceMode ? t("disableMaintenance") : t("enableMaintenance")}
                    </span>
                    <Switch
                      checked={maintenanceMode}
                      disabled={maintenanceLoading || toggling}
                      tabIndex={-1}
                    />
                  </div>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      {maintenanceMode
                        ? t("confirmDisableMaintenance")
                        : t("confirmEnableMaintenance")}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      {maintenanceMode
                        ? t("confirmDisableDescription")
                        : t("confirmEnableDescription")}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={toggleMaintenance}
                      className={maintenanceMode ? "" : "bg-amber-600 hover:bg-amber-700"}
                    >
                      {maintenanceMode ? t("disableMaintenance") : t("enableMaintenance")}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title={t("organizations")}
          value={stats?.organizations.total ?? 0}
          subtitle={t("active", { count: stats?.organizations.active ?? 0 })}
          icon={<Building2 className="w-6 h-6 text-muted-foreground" />}
        />
        <StatCard
          title={t("users")}
          value={stats?.users.total ?? 0}
          subtitle={t("active", { count: stats?.users.active ?? 0 })}
          icon={<Users className="w-6 h-6 text-muted-foreground" />}
        />
        <StatCard
          title={t("models")}
          value={stats?.models.catalog_total ?? 0}
          subtitle={t("activated", { count: stats?.models.activated_total ?? 0 })}
          icon={<KeyRound className="w-6 h-6 text-muted-foreground" />}
        />
        <StatCard
          title={t("creditBalance")}
          value={stats?.credits.total_balance ?? 0}
          subtitle={t("acrossAllOrgs")}
          icon={<Coins className="w-6 h-6 text-muted-foreground" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="border-border">
          <CardHeader>
            <CardTitle className="text-lg font-serif">{t("creditsOverview")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold text-primary">
              {(stats?.credits.total_balance ?? 0).toLocaleString()}
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              {t("totalCreditsAllOrgs")}
            </p>
          </CardContent>
        </Card>

        <Card className="border-border">
          <CardHeader>
            <CardTitle className="text-lg font-serif">{t("quickActions")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <QuickAction href="/admin/organizations" label={t("manageOrganizations")} />
            <QuickAction href="/admin/users" label={t("manageUsers")} />
            <QuickAction href="/admin/api-keys" label={t("manageApiKeys")} />
            <QuickAction href="/admin/credits" label={t("adjustCredits")} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({
  title,
  value,
  subtitle,
  icon
}: {
  title: string;
  value: number;
  subtitle: string;
  icon: ReactNode;
}) {
  return (
    <Card className="border-border">
      <CardContent className="pt-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-3xl font-bold text-foreground mt-1">{value}</p>
            <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
          </div>
          {icon}
        </div>
      </CardContent>
    </Card>
  );
}

function QuickAction({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="block p-3 border border-border hover:bg-muted transition-colors"
    >
      <span className="text-sm font-medium">{label}</span>
      <span className="float-right text-muted-foreground">→</span>
    </a>
  );
}
