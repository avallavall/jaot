"use client";

import { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { translateApiError } from "@/lib/errors";
import { loginPathReturningTo } from "@/lib/return-path";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { CheckCircle, XCircle, Loader2 } from "lucide-react";
import Link from "next/link";

interface JoinPageProps {
  params: Promise<{ token: string }>;
}

type JoinState = "loading" | "success" | "error";

export default function JoinPage({ params }: JoinPageProps) {
  const { token } = use(params);
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  const t = useTranslations("auth");
  const tError = useTranslations("errors.codes");
  const [joinState, setJoinState] = useState<JoinState>("loading");
  const [errorMessage, setErrorMessage] = useState("");

  // Handle unauthenticated redirect
  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      // Come back HERE after signing in. The invite used to be stashed in
      // sessionStorage and accepted inside AuthContext, whose catch swallowed
      // the failure — so an invite that had been revoked landed the person on
      // /studio with nothing said, while the same link opened while already
      // signed in showed a proper "Invite not valid" page. What they learned
      // depended on whether they happened to be logged in. This page accepts
      // the invite and reports what happened, whichever way they arrived.
      toast.info(t("join.signInToAccept"));
      router.push(loginPathReturningTo(`/join/${token}`));
    }
  }, [isAuthenticated, isLoading, token, router, t]);

  // Accept the invite when authenticated
  useEffect(() => {
    if (isLoading || !isAuthenticated) return;

    const accept = async () => {
      try {
        await api.acceptInvite(token);
        setJoinState("success");
      } catch (err) {
        // The API's `detail` is English by contract; render the error's code
        // instead, and the translated generic message when there is none.
        setErrorMessage(translateApiError(err, tError, t("join.acceptFailed")));
        setJoinState("error");
      }
    };
    accept();
  }, [isAuthenticated, isLoading, token, t, tError]);

  // Show loading while auth is resolving or redirect is pending
  if (isLoading || (!isAuthenticated && joinState === "loading")) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-primary" />
          <p className="text-muted-foreground">{t("join.processing")}</p>
        </div>
      </div>
    );
  }

  if (joinState === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-primary" />
          <p className="text-muted-foreground">{t("join.accepting")}</p>
        </div>
      </div>
    );
  }

  if (joinState === "success") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md mx-4">
          <CheckCircle className="w-16 h-16 mx-auto mb-4 text-green-500" />
          <h1 className="text-2xl font-bold mb-2">{t("join.successTitle")}</h1>
          <p className="text-muted-foreground mb-6">
            {t("join.successMessage")}
          </p>
          <Button asChild>
            <Link href="/workspace/workspaces">{t("join.goToWorkspaces")}</Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center max-w-md mx-4">
        <XCircle className="w-16 h-16 mx-auto mb-4 text-destructive" />
        <h1 className="text-2xl font-bold mb-2">{t("join.errorTitle")}</h1>
        {/* One sentence. The generic "may have expired, been revoked, or
            already been used" was printed above the server's own reason, so
            the page said the same thing twice in both languages. The generic
            one is the fallback for a refusal that named nothing. */}
        <p className="text-muted-foreground mb-4" data-testid="join-error-message">
          {errorMessage || t("join.errorMessage")}
        </p>
        <div className="flex gap-3 justify-center">
          <Button asChild>
            <Link href="/workspace">{t("join.goToDashboard")}</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/login">{t("join.signIn")}</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
