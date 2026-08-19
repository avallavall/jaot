"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";

/**
 * What a deleted model's URL shows.
 *
 * A link to a model somebody deleted used to land on the model list with
 * nothing said, so the click looked like it had missed. Worse on the Solve
 * tab: `/solve/<id>/history` redirects there, and the workbench opened in
 * full — tabs, solver picker and an enabled Solve button — over a model that
 * no longer exists.
 *
 * Runs outlive their model, which is why the second line says so: whoever
 * followed the link may only want the numbers, and those are still there.
 */
export function MissingModel() {
  const t = useTranslations("studio.missing");

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center px-6 text-center">
      <h1 className="text-2xl font-semibold mb-3">{t("title")}</h1>
      <p className="text-muted-foreground max-w-md mb-8">{t("body")}</p>
      <div className="flex flex-col sm:flex-row gap-4 justify-center">
        <Link href="/studio">
          <Button>{t("backToModels")}</Button>
        </Link>
        <Link href="/solve/executions">
          <Button variant="outline">{t("seeRuns")}</Button>
        </Link>
      </div>
    </div>
  );
}
