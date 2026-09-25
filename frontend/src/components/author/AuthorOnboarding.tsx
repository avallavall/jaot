"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Circle } from "lucide-react";

import { api } from "@/lib/api";
import type { OnboardingStatus } from "@/lib/types";
import { Link } from "@/i18n/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * The 3-step checklist the backend has always served and nobody rendered. Its
 * links used to 404 (two pointed at routes that never existed, one at a page
 * that does not hold what the step measures) — the backend now returns real
 * ones, and `tests/test_author_area.py` fails if that regresses.
 */
interface AuthorOnboardingProps {
  /** Change it to load the checklist again, after the page changed a listing. */
  refreshKey?: number;
}

export function AuthorOnboarding({ refreshKey = 0 }: AuthorOnboardingProps) {
  const t = useTranslations("author.onboarding");
  const [status, setStatus] = useState<OnboardingStatus | null>(null);

  // Withdraw and "Publish again" on the same page change what the steps
  // measure. The checklist loaded once, so "Publish your first model" kept
  // its old state until a reload. A late answer never replaces a newer one.
  useEffect(() => {
    let cancelled = false;
    api
      .getAuthorOnboardingStatus()
      .then((next) => {
        if (!cancelled) setStatus(next);
      })
      .catch(() => {
        if (!cancelled) setStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  // Nothing to nag about once every step is done.
  if (!status || status.all_complete) return null;

  // The keys come from the server, so a step the backend adds before the locales
  // catch up arrives here unnamed. `t()` does not throw on a missing message —
  // measured against next-intl 4.13: the default handler logs and returns the key
  // path — so the failure mode is not a blank page, it is a checklist item that
  // reads "author.onboarding.steps.<key>.title" at the reader. Skip what we
  // cannot name; a card with nothing nameable left does not render at all.
  const steps = status.steps.filter(
    (step) =>
      t.has(`steps.${step.key}.title`) &&
      (step.completed ||
        (t.has(`steps.${step.key}.description`) && t.has(`steps.${step.key}.cta`))),
  );
  if (steps.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-medium">{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="space-y-3">
          {steps.map((step) => (
            <li key={step.key} className="flex items-start gap-3">
              {step.completed ? (
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
              ) : (
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              )}
              <div className="min-w-0">
                <p
                  className={
                    step.completed ? "text-sm text-muted-foreground line-through" : "text-sm"
                  }
                >
                  {t(`steps.${step.key}.title`)}
                </p>
                {!step.completed && (
                  <p className="text-xs text-muted-foreground">
                    {t(`steps.${step.key}.description`)}{" "}
                    <Link href={step.link} className="underline underline-offset-2">
                      {t(`steps.${step.key}.cta`)}
                    </Link>
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
