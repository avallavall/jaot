"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { useAuth } from "@/contexts/AuthContext";
import { getPasswordStrength, isPasswordTooSimple } from "@/lib/password-strength";
import { RETURN_PARAM, defaultLandingPath, safeReturnPath } from "@/lib/return-path";

export default function SignupPage() {
  const router = useRouter();
  const { loginWithEmail, isAuthenticated, isLoading, user } = useAuth();
  const t = useTranslations("auth");
  const locale = useLocale();

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [registrationDisabled, setRegistrationDisabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tosAccepted, setTosAccepted] = useState(false);

  const strength = password ? getPasswordStrength(password) : null;

  // /login sends a signed-in visitor on; /signup used to render the form under
  // the welcome wizard, and going through with it would create a second
  // account and organisation and swap the session for it.
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      const next = new URLSearchParams(window.location.search).get(RETURN_PARAM);
      router.push(safeReturnPath(next, defaultLandingPath(user?.is_admin)));
    }
  }, [isLoading, isAuthenticated, user, router]);

  // Ask before drawing the form. A closed instance used to answer only on
  // submit: the visitor filled in five fields, pressed the button, and had
  // everything they typed replaced by "Registration is currently closed".
  // A failure here leaves the form up — refusing to draw it because one read
  // did not answer would be worse than the 503 it is guarding against.
  useEffect(() => {
    let cancelled = false;
    api
      .signupStatus()
      .then((status) => {
        if (!cancelled && !status.enabled) setRegistrationDisabled(true);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError(t("signup.passwordsNoMatch"));
      return;
    }

    // Must match the backend rule (app/schemas/auth.py: min_length=12)
    if (password.length < 12) {
      setError(t("signup.passwordMinLength"));
      return;
    }

    // Length is not variety: "aaaaaaaaaaaa" passed every check the form had and
    // the meter under the field called it weak while the account was created.
    if (isPasswordTooSimple(password)) {
      setError(t("signup.passwordTooSimple"));
      return;
    }

    if (!tosAccepted) {
      setError(t("signup.tosRequired"));
      return;
    }

    setLoading(true);

    try {
      await api.signupWithEmail({
        email,
        name,
        organization_name: organizationName,
        password,
        confirm_password: confirmPassword,
        tos_accepted: tosAccepted,
        // Remembered on the account: the verification mail that follows in a
        // second, and every email after it, are sent in this language.
        locale,
      });

      // The signup response carries an account API key. It is deliberately NOT
      // written to localStorage. Doing so left a live, non-expiring credential
      // on the machine of everyone who ever signed up here, and the app sent it
      // as a Bearer token on every request from then on — while every other
      // session in the product runs on cookies, which is the decision recorded
      // in AuthContext's email-login path. The user is never shown that key
      // either; keys meant for programmatic use are minted, and revealed once,
      // on /workspace/api-keys.

      // Signup endpoint already sets JWT cookies, so log in with email to set
      // AuthContext state (this will use the cookies already set)
      await loginWithEmail(email, password);

      // Back to where they were heading — an invite link, usually. Landing on
      // the studio instead left the invite unaccepted and nothing said.
      const next = new URLSearchParams(window.location.search).get(RETURN_PARAM);
      router.push(safeReturnPath(next, "/studio"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setRegistrationDisabled(true);
        setError(t("signup.registrationDisabled"));
      } else {
        setError(getErrorMessage(err, t("signup.signupFailed")));
      }
    } finally {
      setLoading(false);
    }
  };

  // Same guard /login carries: do not paint a form that is about to be replaced
  // by a redirect.
  if (!isLoading && isAuthenticated) {
    return null;
  }

  if (registrationDisabled) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md border-border shadow-lg">
          <CardHeader className="text-center space-y-2">
            <CardTitle className="text-3xl font-serif text-primary">
              {t("signup.brandName")}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p className="text-muted-foreground">
              {t("signup.registrationDisabled")}
            </p>
            <p className="text-sm text-muted-foreground">
              {t("signup.contactSupport")}
            </p>
            <Link href="/login">
              <Button variant="outline" className="w-full">
                {t("signup.backToLogin")}
              </Button>
            </Link>
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
            {t("signup.brandName")}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {t("signup.subtitle")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="signup-email">{t("signup.emailLabel")}</Label>
              <Input
                id="signup-email"
                type="email"
                placeholder={t("signup.emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="signup-name">{t("signup.nameLabel")}</Label>
              <Input
                id="signup-name"
                type="text"
                placeholder={t("signup.namePlaceholder")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="signup-org">{t("signup.orgLabel")}</Label>
              <Input
                id="signup-org"
                type="text"
                placeholder={t("signup.orgPlaceholder")}
                value={organizationName}
                onChange={(e) => setOrganizationName(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="signup-password">{t("signup.passwordLabel")}</Label>
              <Input
                id="signup-password"
                type="password"
                placeholder={t("signup.passwordPlaceholder")}
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
              <Label htmlFor="signup-confirm">{t("signup.confirmPasswordLabel")}</Label>
              <Input
                id="signup-confirm"
                type="password"
                placeholder={t("signup.confirmPasswordPlaceholder")}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={12}
              />
            </div>

            <div className="flex items-start space-x-2">
              <Checkbox
                id="tos-accept"
                checked={tosAccepted}
                onCheckedChange={(checked) => setTosAccepted(checked === true)}
                required
              />
              <Label htmlFor="tos-accept" className="text-sm leading-tight font-normal">
                {t.rich("signup.tosAgree", {
                  terms: (chunks) => (
                    <a href="/terms" target="_blank" rel="noopener noreferrer" className="text-primary underline">
                      {chunks}
                    </a>
                  ),
                  privacy: (chunks) => (
                    <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-primary underline">
                      {chunks}
                    </a>
                  ),
                })}
              </Label>
            </div>

            {error && (
              <div className="p-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={!tosAccepted || loading}>
              {loading ? t("signup.creating") : t("signup.submit")}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            {t.rich("signup.hasAccount", {
              link: (chunks) => (
                <Link href="/login" className="text-primary underline">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
