"use client";

import { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
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
  const [joinState, setJoinState] = useState<JoinState>("loading");
  const [errorMessage, setErrorMessage] = useState("");

  // Handle unauthenticated redirect
  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      // Store the token so we can accept after login
      sessionStorage.setItem("jaot_pending_invite", token);
      toast.info(t("join.signInToAccept"));
      router.push("/login");
    }
  }, [isAuthenticated, isLoading, token, router, t]);

  // Accept the invite when authenticated
  useEffect(() => {
    if (isLoading || !isAuthenticated) return;

    const accept = async () => {
      try {
        await api.acceptInvite(token);
        sessionStorage.removeItem("jaot_pending_invite");
        setJoinState("success");
      } catch (err) {
        const msg = err instanceof Error ? err.message : t("join.acceptFailed");
        setErrorMessage(msg);
        setJoinState("error");
      }
    };
    accept();
  }, [isAuthenticated, isLoading, token, t]);

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
        <p className="text-muted-foreground mb-2">
          {t("join.errorMessage")}
        </p>
        {errorMessage && (
          <p className="text-sm text-destructive mb-4 bg-destructive/10 rounded p-2">
            {errorMessage}
          </p>
        )}
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
