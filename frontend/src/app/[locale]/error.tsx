"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";

// Branded error boundary for everything below the [locale] segment (audit F-03).
// Renders inside [locale]/layout.tsx, so i18n providers and globals.css are
// available. Errors thrown by the layout itself escalate to global-error.tsx.
export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("errors.appError");

  useEffect(() => {
    // Surface the error in the browser console / monitoring; the UI shows
    // only a localized, user-safe message (never the raw error).
    console.error("[error-boundary]", error);
  }, [error]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background text-foreground px-6 text-center">
      <Link href="/" className="text-xl font-serif text-primary mb-8">
        JAOT
      </Link>
      <h1 className="text-2xl font-semibold mb-3">{t("title")}</h1>
      <p className="text-muted-foreground max-w-md mb-2">{t("message")}</p>
      {error.digest && (
        <p className="text-xs text-muted-foreground">
          {t("digest", { digest: error.digest })}
        </p>
      )}
      <div className="flex flex-col sm:flex-row gap-4 justify-center mt-8">
        <Button onClick={reset}>{t("retry")}</Button>
        <Link href="/">
          <Button variant="outline">{t("backHome")}</Button>
        </Link>
      </div>
    </div>
  );
}
