"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
// next-intl's router/Link preserve the active locale on client-side navigation;
// next/navigation does NOT (push("/solve") would drop the locale chosen on the
// public home and fall back to the default). See bugfix B2.
// next-intl's router/Link preserve the active locale on client-side navigation;
// next/navigation does NOT (push("/solve") would drop the locale chosen on the
// public home and fall back to the default). See bugfix B2.
import { useRouter, Link } from "@/i18n/navigation";
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
import { translateApiError } from "@/lib/errors";
import {
  EXPIRED_PARAM,
  RETURN_PARAM,
  defaultLandingPath,
  safeReturnPath,
} from "@/lib/return-path";

export default function LoginPage() {
  const router = useRouter();
  const { loginWithEmail, isAuthenticated, isLoading, user } = useAuth();
  const t = useTranslations("auth");
  const tError = useTranslations("errors.codes");

  // Email login state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [emailLoading, setEmailLoading] = useState(false);

  // Redirect once authenticated — back to the page that sent us here when a
  // protected route did, otherwise to the usual landing page. `next` is attacker
  // -reachable (it is in the URL), so it goes through safeReturnPath first.
  // Read off `window` inside the effect to keep this page statically renderable;
  // useSearchParams would demand a Suspense boundary for no gain.
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      const next = new URLSearchParams(window.location.search).get(RETURN_PARAM);
      router.push(safeReturnPath(next, defaultLandingPath(user?.is_admin)));
    }
  }, [isLoading, isAuthenticated, user, router]);

  // Say why they are here when a session ran out under them. Read off
  // `window` for the same reason the redirect above does.
  const [sessionExpired, setSessionExpired] = useState(false);
  useEffect(() => {
    setSessionExpired(
      new URLSearchParams(window.location.search).get(EXPIRED_PARAM) === "1",
    );
  }, []);

  // Somebody invited who has no account yet arrives here with ?next=/join/…
  // and leaves for signup. Without carrying it they sign up and land on the
  // studio, and the invite is never accepted.
  const [signupHref, setSignupHref] = useState("/signup");
  useEffect(() => {
    const next = new URLSearchParams(window.location.search).get(RETURN_PARAM);
    setSignupHref(next ? `/signup?${RETURN_PARAM}=${encodeURIComponent(next)}` : "/signup");
  }, []);

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setEmailError("");
    setEmailLoading(true);

    try {
      await loginWithEmail(email, password, rememberMe);
      // After login, user state will update and the useEffect above handles redirect
    } catch (err) {
      // The API's `detail` is English by contract; render the error's code
      // instead, and the translated generic message when there is none.
      setEmailError(translateApiError(err, tError, t("login.loginFailed")));
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
            {sessionExpired && !emailError && (
              <div className="p-3 text-sm bg-muted border border-border rounded-md" role="status">
                {t("login.sessionExpired")}
              </div>
            )}
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
                  <Link href={signupHref} className="text-primary underline">
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
