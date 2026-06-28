"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";

/**
 * Studio home — "My Models" list. P0 placeholder: heading + "New model" entry.
 * The rich version-aware model list lands in a later slice.
 */
export default function StudioHomePage() {
  const t = useTranslations("studio");
  const router = useRouter();

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{t("myModels")}</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {t("myModelsSubtitle")}
          </p>
        </div>
        <Button onClick={() => router.push("/studio/new")}>
          {t("newModel")}
        </Button>
      </div>

      <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
        {t("myModelsEmpty")}
      </div>
    </div>
  );
}
