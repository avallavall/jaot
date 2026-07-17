"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { useDslStatus } from "@/hooks/useDslStatus";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { DatasetsCard } from "../datasets/DatasetsCard";

/**
 * The "Datos" tab (S4) — ALL input data for the model, kept apart from its
 * structure: the project's named datasets (list / CRUD; skeleton, table editor
 * and file import land with S2a/S2b/S2c). The charter: no model structure
 * editing here — that's Build's job, and the empty state says so.
 *
 * Only reachable while JAOT_DSL is on (the tab shares the JModel lens gate);
 * a direct URL with the flag off gets an explanatory placeholder, mirroring
 * how `?lens=jmodel` falls back when gated off.
 */
export function DataPanel() {
  const t = useTranslations("studio");
  const dslEnabled = useDslStatus();
  const modelId = useModelProjectStore((s) => s.modelId);
  const isPersisted = !!modelId && modelId !== "new";

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto" data-testid="studio-data-panel">
        <div className="mb-4">
          <h2 className="flex items-center gap-1.5 text-lg font-semibold">
            {t("dataTitle")}
            <HelpTooltip content={t("helpTooltips.datasets")} />
          </h2>
          <p className="text-sm text-muted-foreground">{t("dataSubtitle")}</p>
        </div>

        {!dslEnabled ? (
          <p className="rounded-lg border p-4 text-sm text-muted-foreground">
            {t("dataUnavailable")}
          </p>
        ) : !isPersisted ? (
          <p className="rounded-lg border p-4 text-sm text-muted-foreground">
            {t("dataNeedsSave")}
          </p>
        ) : (
          <>
            <DatasetsCard />
            {/* Pipeline glue: data fills a declaration-only JModel — point at the
                lens where that structure is written instead of dead-ending here. */}
            <p className="mt-4 text-xs text-muted-foreground">
              {t("dataExplainer")}{" "}
              <Link
                href={`/studio/${modelId}/build?lens=jmodel`}
                className="text-primary hover:underline"
                data-testid="studio-data-open-jmodel"
              >
                {t("dataGoToJModel")}
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
