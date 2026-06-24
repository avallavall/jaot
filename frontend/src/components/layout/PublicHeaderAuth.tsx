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

  if (isAuthenticated) {
    return (
      <Link href="/workspace">
        <Button size="sm">{t("goToDashboard")}</Button>
      </Link>
    );
  }

  return (
    <Link href="/login">
      <Button size="sm">{t("signIn")}</Button>
    </Link>
  );
}
