"use client";

import { Suspense } from "react";
import { useTranslations } from "next-intl";
import { ResetPasswordForm } from "./ResetPasswordForm";

function ResetPasswordFallback() {
  const t = useTranslations("auth");
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-muted-foreground">{t("protectedRoute.loading")}</div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
