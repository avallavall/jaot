"use client";

import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { NotificationPreferences } from "@/components/seller/NotificationPreferences";
import { Skeleton } from "@/components/ui/skeleton";

export default function WorkspaceSettingsPage() {
  const t = useTranslations("settings");
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("description")}</p>
      </div>

      {/* Seller Notification Preferences - only visible for org users */}
      <NotificationPreferences />
    </div>
  );
}
