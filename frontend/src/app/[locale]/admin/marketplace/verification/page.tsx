"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import type { AdminVerificationEntry } from "@/lib/types";
import { VerificationQueue } from "@/components/admin/VerificationQueue";
import { Skeleton } from "@/components/ui/skeleton";

export default function AdminVerificationPage() {
  const t = useTranslations("admin.marketplace");
  const { user, isLoading: authLoading } = useAuth();
  const [requests, setRequests] = useState<AdminVerificationEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAdminVerificationRequests();
      setRequests(data);
    } catch (err) {
      console.warn('Failed to load verification requests:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authLoading && user?.is_admin) {
      loadData();
    }
  }, [authLoading, user, loadData]);

  if (authLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (!user?.is_admin) return null;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("verificationRequests")}</h1>
        <p className="text-muted-foreground">{t("verificationDesc")}</p>
      </div>

      {loading ? (
        <Skeleton className="h-96" />
      ) : (
        <VerificationQueue requests={requests} onUpdate={loadData} />
      )}
    </div>
  );
}
