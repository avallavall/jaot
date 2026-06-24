"use client";

import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";

export function UsageIndicator() {
  const { organization } = useAuth();
  const t = useTranslations("common");

  if (!organization) return null;

  const plan = organization.plan || "free";

  return (
    <div className="px-4 py-2 border-t border-sidebar-border">
      <div className="flex items-center justify-between text-xs text-sidebar-foreground/75">
        <span className="font-medium uppercase tracking-wider">{t("tier.plan", { plan })}</span>
        {organization.credits_balance != null && (
          <span>{t("tier.creditsRemaining", { count: organization.credits_balance })}</span>
        )}
      </div>
    </div>
  );
}
