"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const t = useTranslations("auth");
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await api.forgotPassword(email);
      setSubmitted(true);
    } catch {
      // Always show success message regardless of response to prevent email enumeration
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md border-border shadow-lg">
        <CardHeader className="text-center space-y-2">
          <CardTitle className="text-3xl font-serif text-primary">
            {t("forgotPassword.brandName")}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {t("forgotPassword.subtitle")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {submitted ? (
            <div className="space-y-4">
              <div className="p-4 text-sm text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md">
                {t("forgotPassword.successMessage")}
              </div>
              <p className="text-center text-sm text-muted-foreground">
                <Link
                  href="/login"
                  className="text-primary underline hover:opacity-80"
                >
                  {t("forgotPassword.backToLogin")}
                </Link>
              </p>
            </div>
          ) : (
            <>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="reset-email">{t("forgotPassword.emailLabel")}</Label>
                  <Input
                    id="reset-email"
                    type="email"
                    placeholder={t("forgotPassword.emailPlaceholder")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>

                {error && (
                  <div className="p-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
                    {error}
                  </div>
                )}

                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? t("forgotPassword.sending") : t("forgotPassword.submit")}
                </Button>
              </form>

              <p className="mt-4 text-center text-sm text-muted-foreground">
                {t.rich("forgotPassword.rememberPassword", {
                  link: (chunks) => (
                    <Link
                      href="/login"
                      className="text-primary underline hover:opacity-80"
                    >
                      {chunks}
                    </Link>
                  ),
                })}
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
