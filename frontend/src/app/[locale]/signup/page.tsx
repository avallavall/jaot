"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
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
import { getPasswordStrength } from "@/lib/password-strength";

export default function SignupPage() {
  const router = useRouter();
  const { loginWithEmail } = useAuth();
  const t = useTranslations("auth");

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

    if (!tosAccepted) {
      setError(t("signup.tosRequired"));
      return;
    }

    setLoading(true);

    try {
      const result = await api.signupWithEmail({
        email,
        name,
        organization_name: organizationName,
        // Self-serve signup is free-tier only; paid plans go through Stripe checkout.
        plan: "free",
        password,
        confirm_password: confirmPassword,
        tos_accepted: tosAccepted,
      });

      // Store the returned API key for SDK/programmatic use
      if (result.api_key) {
        localStorage.setItem("jaot_api_key", result.api_key);
      }

      // Signup endpoint already sets JWT cookies, so log in with email to set
      // AuthContext state (this will use the cookies already set)
      await loginWithEmail(email, password);

      // Redirect to main app
      router.push("/solve");
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
