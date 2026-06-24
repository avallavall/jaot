"use client";

import { Suspense } from "react";
import { useTranslations } from "next-intl";
import { VerifyEmailHandler } from "./VerifyEmailHandler";

function VerifyEmailFallback() {
  const t = useTranslations("auth");
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-muted-foreground">{t("verifyEmail.verifying")}</div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<VerifyEmailFallback />}>
      <VerifyEmailHandler />
    </Suspense>
  );
}
