"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";

/**
 * Discoverability nudge shown in AI surfaces: "you can use your own Anthropic API
 * key here" → links to the org settings where the owner can add it (BYOK). Purely
 * informational; safe to render for any user.
 */
export function ByokHint() {
  const t = useTranslations("settings.byok");
  const locale = useLocale();
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
      <p>
        {t("hintText")}{" "}
        <Link
          href={`/${locale}/workspace/settings`}
          className="font-medium text-primary hover:underline"
        >
          {t("hintLink")}
        </Link>
      </p>
    </div>
  );
}
