"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
// Use next-intl's router so redirects preserve the active locale (see bugfix B2).
import { useRouter, usePathname } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { loginPathReturningTo } from "@/lib/return-path";
import { EmailVerificationBanner } from "@/components/auth/EmailVerificationBanner";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export function ProtectedRoute({ children, requireAdmin = false }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, user, sessionEnded } = useAuth();
  const router = useRouter();
  const pathname = usePathname(); // locale-free — the router re-applies the prefix
  const t = useTranslations("auth");

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated) {
      // Hand the page they asked for to the login screen, so signing in finishes
      // the navigation they started instead of dumping them on /studio.
      // The query string is read off `window` rather than through
      // useSearchParams: this component wraps every protected page, and the hook
      // would force a Suspense boundary (and dynamic rendering) on all of them.
      // Inside an effect there is always a browser.
      //
      // This is the ONLY place a missing session sends anybody to /login. The
      // component wraps exactly the pages that need one, so a visitor reading
      // the home page, the marketplace or the docs is never moved.
      router.push(
        loginPathReturningTo(pathname, window.location.search, sessionEnded),
      );
      return;
    }

    if (requireAdmin && !user?.is_admin) {
      router.push("/studio");
    }
  }, [isAuthenticated, isLoading, requireAdmin, user, router, pathname, sessionEnded]);

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
