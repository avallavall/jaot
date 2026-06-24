"use client";

import { useAuth } from "@/contexts/AuthContext";
import { useTranslations } from "next-intl";

export function EmailVerificationBanner() {
  const { user, isAuthenticated } = useAuth();
  const t = useTranslations("auth");

  if (!isAuthenticated || !user || user.email_verified !== false) return null;

  return (
    <div className="bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800 px-4 py-2 text-center text-sm text-yellow-800 dark:text-yellow-200">
      {t("emailBanner.message")}
    </div>
  );
}
