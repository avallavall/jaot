"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";

export function VerifyEmailHandler() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const t = useTranslations("auth");

  const [status, setStatus] = useState<"loading" | "success" | "error">(
    token ? "loading" : "error"
  );
  const [message, setMessage] = useState(
    token ? "" : t("verifyEmail.invalidLink")
  );

  useEffect(() => {
    if (!token) return; // state already set by initializer -- just skip

    const verify = async () => {
      try {
        const result = await api.verifyEmail(token);
        if (result.success) {
          setStatus("success");
          setMessage(result.message || t("verifyEmail.defaultSuccess"));
        } else {
          setStatus("error");
          setMessage(result.message || t("verifyEmail.defaultError"));
        }
      } catch (err) {
        setStatus("error");
        setMessage(
          err instanceof Error
            ? err.message
            : t("verifyEmail.verificationFailed")
        );
      }
    };

    verify();
  }, [token, t]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md border-border shadow-lg">
        <CardHeader className="text-center space-y-2">
          <CardTitle className="text-3xl font-serif text-primary">
            {t("verifyEmail.brandName")}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {t("verifyEmail.subtitle")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status === "loading" && (
            <div className="text-center py-8">
              <div className="text-muted-foreground">
                {t("verifyEmail.verifying")}
              </div>
            </div>
          )}

          {status === "success" && (
            <div className="space-y-4">
              <div className="p-4 text-sm text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md">
                {message}
              </div>
              <p className="text-center text-sm text-muted-foreground">
                <Link
                  href="/solve"
                  className="text-primary hover:underline"
                >
                  {t("verifyEmail.continueToDashboard")}
                </Link>
              </p>
            </div>
          )}

          {status === "error" && (
            <div className="space-y-4">
              <div className="p-4 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
                {message}
              </div>
              <p className="text-center text-sm text-muted-foreground">
                <Link
                  href="/login"
                  className="text-primary hover:underline"
                >
                  {t("verifyEmail.goToLogin")}
                </Link>
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
