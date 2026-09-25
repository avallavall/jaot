"use client";

import { useEffect, useState, use } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { translateApiError } from "@/lib/errors";
import { loginPathReturningTo, signupPathForInvite } from "@/lib/return-path";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { CheckCircle, XCircle, Loader2, UserPlus } from "lucide-react";
import Link from "next/link";

interface JoinPageProps {
  params: Promise<{ token: string }>;
}

type JoinState = "loading" | "success" | "error";

export default function JoinPage({ params }: JoinPageProps) {
  const { token } = use(params);
  const { isAuthenticated, isLoading, logout } = useAuth();
  const t = useTranslations("auth");
  const tError = useTranslations("errors.codes");
  const [joinState, setJoinState] = useState<JoinState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [errorCode, setErrorCode] = useState<string | undefined>();

  // Accept the invite when authenticated. An anonymous visitor is not moved:
  // the page below offers both ways in. It used to send everybody to /login,
  // and an invited person with no account had no account to log in with.
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
        setErrorCode(err instanceof ApiError ? err.code : undefined);
        setJoinState("error");
      }
    };
    accept();
  }, [isAuthenticated, isLoading, token, t, tError]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-primary" />
          <p className="text-muted-foreground">{t("join.processing")}</p>
        </div>
      </div>
    );
  }

  // Not signed in. Creating an account from here carries the invite through
  // signup, and the new account is made inside the inviting organization.
  // Signing in comes back here to accept.
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md mx-4">
          <UserPlus className="w-16 h-16 mx-auto mb-4 text-primary" />
          <h1 className="text-2xl font-bold mb-2">{t("join.invitedTitle")}</h1>
          <p className="text-muted-foreground mb-6">{t("join.invitedMessage")}</p>
          <div className="flex gap-3 justify-center">
            <Button asChild>
              <Link href={signupPathForInvite(token)}>{t("join.createAccount")}</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href={loginPathReturningTo(`/join/${token}`)}>{t("join.signIn")}</Link>
            </Button>
          </div>
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

  // Signed in with an account of another organization. An account belongs to
  // one organization, so this one cannot join. The way that works is a new
  // account made from this link, which needs signing out first.
  const otherOrganization = errorCode === "invite.other_organization";

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
          {otherOrganization ? (
            <Button onClick={() => logout(signupPathForInvite(token))}>
              {t("join.signOutAndCreate")}
            </Button>
          ) : (
            <Button asChild>
              <Link href="/workspace">{t("join.goToDashboard")}</Link>
            </Button>
          )}
          {otherOrganization ? (
            <Button variant="outline" asChild>
              <Link href="/workspace">{t("join.goToDashboard")}</Link>
            </Button>
          ) : (
            <Button variant="outline" asChild>
              <Link href="/login">{t("join.signIn")}</Link>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
