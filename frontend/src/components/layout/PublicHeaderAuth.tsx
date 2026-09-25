"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";

export function PublicHeaderAuth() {
  const { isAuthenticated, isLoading } = useAuth();
  const t = useTranslations("public.nav");

  if (isLoading) {
    return (
      <Button size="sm" variant="ghost" disabled className="w-20">
        <span className="animate-pulse">...</span>
      </Button>
    );
  }

  // One element per action. A <button> inside the <a> is two nested controls
  // for one click, which screen readers announce twice.
  if (isAuthenticated) {
    return (
      <Button asChild size="sm">
        <Link href="/workspace">{t("goToDashboard")}</Link>
      </Button>
    );
  }

  return (
    <Button asChild size="sm">
      <Link href="/login">{t("signIn")}</Link>
    </Button>
  );
}
