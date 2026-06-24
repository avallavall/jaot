"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { EmailVerificationBanner } from "@/components/auth/EmailVerificationBanner";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export function ProtectedRoute({ children, requireAdmin = false }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, user } = useAuth();
  const router = useRouter();
  const t = useTranslations("auth");

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated) {
      router.push("/login");
      return;
    }

    if (requireAdmin && !user?.is_admin) {
      router.push("/solve");
    }
  }, [isAuthenticated, isLoading, requireAdmin, user, router]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">{t("protectedRoute.loading")}</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  if (requireAdmin && !user?.is_admin) {
    return null;
  }

  return (
    <>
      <EmailVerificationBanner />
      {children}
    </>
  );
}
