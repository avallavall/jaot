"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
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
import { getPasswordStrength } from "@/lib/password-strength";

export function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const t = useTranslations("auth");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const strength = password ? getPasswordStrength(password) : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!token) {
      setError(t("resetPassword.invalidResetLink"));
      return;
    }

    if (password !== confirmPassword) {
      setError(t("resetPassword.passwordsNoMatch"));
      return;
    }

    // Must match the backend rule (app/schemas/auth.py: min_length=12)
    if (password.length < 12) {
      setError(t("resetPassword.passwordMinLength"));
      return;
    }

    setLoading(true);

    try {
      await api.resetPassword(token, password);
      setSuccess(true);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("resetPassword.resetFailed")
      );
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md border-border shadow-lg">
          <CardHeader className="text-center space-y-2">
            <CardTitle className="text-3xl font-serif text-primary">
              {t("resetPassword.brandName")}
            </CardTitle>
            <CardDescription className="text-muted-foreground">
              {t("resetPassword.invalidLinkTitle")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="p-4 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
              {t("resetPassword.invalidLinkMessage")}
            </div>
            <p className="mt-4 text-center text-sm text-muted-foreground">
              <Link
                href="/forgot-password"
                className="text-primary hover:underline"
              >
                {t("resetPassword.requestNewLink")}
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md border-border shadow-lg">
        <CardHeader className="text-center space-y-2">
          <CardTitle className="text-3xl font-serif text-primary">
            {t("resetPassword.brandName")}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {t("resetPassword.subtitle")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {success ? (
            <div className="space-y-4">
              <div className="p-4 text-sm text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md">
                {t("resetPassword.successMessage")}
              </div>
              <p className="text-center text-sm text-muted-foreground">
                <Link
                  href="/login"
                  className="text-primary hover:underline"
                >
                  {t("resetPassword.goToLogin")}
                </Link>
              </p>
            </div>
          ) : (
            <>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="new-password">{t("resetPassword.passwordLabel")}</Label>
                  <Input
                    id="new-password"
                    type="password"
                    placeholder={t("resetPassword.passwordPlaceholder")}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={12}
                  />
                  {strength && (
                    <div className="space-y-1">
                      <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all ${strength.color}`}
                          style={{ width: `${strength.score}%` }}
                        />
                      </div>
                      <p
                        className={`text-xs ${
                          strength.level === "weak"
                            ? "text-red-500"
                            : strength.level === "fair"
                              ? "text-yellow-500"
                              : "text-green-500"
                        }`}
                      >
                        {t(`passwordStrength.${strength.level}`)}
                      </p>
                    </div>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="confirm-new-password">
                    {t("resetPassword.confirmLabel")}
                  </Label>
                  <Input
                    id="confirm-new-password"
                    type="password"
                    placeholder={t("resetPassword.confirmPlaceholder")}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={12}
                  />
                </div>

                {error && (
                  <div className="p-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
                    {error}
                  </div>
                )}

                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? t("resetPassword.resetting") : t("resetPassword.submit")}
                </Button>
              </form>

              <p className="mt-4 text-center text-sm text-muted-foreground">
                <Link
                  href="/forgot-password"
                  className="text-primary hover:underline"
                >
                  {t("resetPassword.requestNewLink")}
                </Link>
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
