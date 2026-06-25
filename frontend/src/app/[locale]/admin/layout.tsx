"use client";

import { useEffect, useMemo, useState } from "react";
import { Sidebar } from "@/components/layout/sidebar";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { LayoutDashboard, Building2, Users, Key, Coins, Settings, ArrowLeft, Package, Activity, Flag, BarChart3, Shield, Star } from "lucide-react";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const t = useTranslations("admin.layout");

  const adminNavItems = useMemo(() => [
    { label: t("nav.dashboard"), href: "/admin", icon: <LayoutDashboard className="w-4 h-4" /> },
    { label: t("nav.platformAnalytics"), href: "/admin/platform", icon: <BarChart3 className="w-4 h-4" /> },
    { label: "─────────", href: "#", icon: null },
    { label: t("nav.organizations"), href: "/admin/organizations", icon: <Building2 className="w-4 h-4" /> },
    { label: t("nav.users"), href: "/admin/users", icon: <Users className="w-4 h-4" /> },
    { label: t("nav.models"), href: "/admin/models", icon: <Package className="w-4 h-4" /> },
    { label: t("nav.apiKeys"), href: "/admin/api-keys", icon: <Key className="w-4 h-4" /> },
    { label: "─────────", href: "#", icon: null },
    { label: t("nav.executions"), href: "/admin/executions", icon: <Activity className="w-4 h-4" /> },
    { label: t("nav.reportedReviews"), href: "/admin/reviews", icon: <Flag className="w-4 h-4" /> },
    { label: t("nav.credits"), href: "/admin/credits", icon: <Coins className="w-4 h-4" /> },
    { label: "─────────", href: "#", icon: null },
    { label: t("nav.marketplace"), href: "#", icon: null },
    { label: t("nav.sellerAnalytics"), href: "/admin/marketplace/seller-analytics", icon: <BarChart3 className="w-4 h-4" /> },
    { label: t("nav.featureAnalytics"), href: "/admin/marketplace/analytics", icon: <Activity className="w-4 h-4" /> },
    { label: t("nav.verification"), href: "/admin/marketplace/verification", icon: <Shield className="w-4 h-4" /> },
    { label: t("nav.promotions"), href: "/admin/marketplace/promotions", icon: <Star className="w-4 h-4" /> },
    { label: "─────────", href: "#", icon: null },
    { label: t("nav.settings"), href: "/admin/settings", icon: <Settings className="w-4 h-4" /> },
    { label: t("nav.backToApp"), href: "/solve", icon: <ArrowLeft className="w-4 h-4" /> },
  ], [t]);
  const [maintenanceActive, setMaintenanceActive] = useState(false);

  useEffect(() => {
    const checkMaintenance = async () => {
      try {
        const data = await api.admin.getSettingsValues("system");
        const value = data.settings?.MAINTENANCE_MODE?.value;
        setMaintenanceActive(value === "true");
      } catch {
        // Silently fail
      }
    };
    checkMaintenance();
  }, []);

  return (
    <ProtectedRoute requireAdmin>
      <div className="flex min-h-screen bg-background">
        <Sidebar
          items={adminNavItems}
          title="JAOT"
          subtitle={t("subtitle")}
        />
        <main id="main-content" className="flex-1">
          {maintenanceActive && (
            <div className="bg-amber-100 dark:bg-amber-900/40 border-b border-amber-300 dark:border-amber-700 px-8 py-3">
              <div className="max-w-[96rem] mx-auto w-full flex items-center justify-between">
                <span className="text-sm font-medium text-amber-800 dark:text-amber-200">
                  {"\u26A0\uFE0F"} {t("maintenanceBanner")}
                </span>
                <Link
                  href="/admin/settings"
                  className="text-sm font-medium text-amber-700 dark:text-amber-300 underline hover:no-underline"
                >
                  {t("manageSettings")}
                </Link>
              </div>
            </div>
          )}
          <div className="p-8">
            <div className="max-w-[96rem] mx-auto w-full">
              <Breadcrumbs />
              {children}
            </div>
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
