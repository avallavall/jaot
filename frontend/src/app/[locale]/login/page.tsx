"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
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
import { useAuth } from "@/contexts/AuthContext";
import { getErrorMessage } from "@/lib/errors";

export default function LoginPage() {
  const router = useRouter();
  const { loginWithEmail, isAuthenticated, isLoading, user } = useAuth();
  const t = useTranslations("auth");

  // Email login state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [emailLoading, setEmailLoading] = useState(false);

  // Redirect if already authenticated
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push(user?.is_admin ? "/admin" : "/solve");
    }
  }, [isLoading, isAuthenticated, user, router]);

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setEmailError("");
    setEmailLoading(true);

    try {
      await loginWithEmail(email, password, rememberMe);
      // After login, user state will update and the useEffect above handles redirect
    } catch (err) {
      setEmailError(getErrorMessage(err, t("login.loginFailed")));
    } finally {
      setEmailLoading(false);
    }
  };

  // Don't render login form if already authenticated (will redirect)
  if (!isLoading && isAuthenticated) {
    return null;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md border-border shadow-lg">
        <CardHeader className="text-center space-y-2">
          <CardTitle className="text-3xl font-serif text-primary">
            {t("login.brandName")}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {t("login.subtitle")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleEmailLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">{t("login.emailLabel")}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t("login.emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="border-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t("login.passwordLabel")}</Label>
              <Input
                id="password"
                type="password"
                placeholder={t("login.passwordPlaceholder")}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="border-input"
              />
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="checkbox"
                id="rememberMe"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="rememberMe" className="text-sm font-normal">
                {t("login.rememberMe")}
              </Label>
            </div>
            {emailError && (
              <div className="p-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
                {emailError}
              </div>
            )}
            <Button
              type="submit"
              className="w-full"
              disabled={emailLoading}
            >
              {emailLoading ? t("login.loggingIn") : t("login.submit")}
            </Button>
          </form>
          <div className="text-center text-sm text-muted-foreground space-y-1 mt-4">
            <p>
              <Link
                href="/forgot-password"
                className="text-primary underline hover:opacity-80"
              >
                {t("login.forgotPassword")}
              </Link>
            </p>
            <p>
              {t.rich("login.noAccount", {
                link: (chunks) => (
                  <Link href="/signup" className="text-primary underline">
                    {chunks}
                  </Link>
                ),
              })}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
