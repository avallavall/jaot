"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { ModelCatalogItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "next-intl";
import { useTemplateTranslation } from "@/hooks/useTemplateTranslation";

function TemplateCard({ template, onClick }: { template: ModelCatalogItem; onClick: () => void }) {
  const t = useTranslations("builder");
  const tmpl = useTemplateTranslation(template.id);
  return (
    <div
      className="border rounded-lg p-4 bg-card hover:border-primary/50 hover:shadow-sm cursor-pointer transition-all"
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
          {t.has(`templates.categories.${template.category}`) ? t(`templates.categories.${template.category}`) : template.category}
        </span>
        <span className="text-xs text-muted-foreground">
          {template.credits_per_execution > 0
            ? t("templates.creditsPerRun", { credits: template.credits_per_execution })
            : t("templates.dynamicCredits")}
        </span>
      </div>
      <h3 className="font-semibold text-sm mt-2">{tmpl.displayName(template.display_name)}</h3>
      {template.description && (
        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{tmpl.description(template.description)}</p>
      )}
      <div className="mt-3 flex items-center justify-between">
        <div className="text-xs text-muted-foreground">
          {template.total_executions > 0 ? t("templates.solves", { count: template.total_executions }) : t("templates.new")}
        </div>
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={(e) => { e.stopPropagation(); onClick(); }}>
          {t("templates.useTemplate")}
        </Button>
      </div>
    </div>
  );
}

export default function TemplatesPage() {
  const t = useTranslations("builder");
  const router = useRouter();
  const [templates, setTemplates] = useState<ModelCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    api
      .getCatalog({ page: 1, page_size: 50 })
      .then((res) => setTemplates(res.items))
      .catch(() => setTemplates([]))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <button
              onClick={() => router.push("/builder")}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {t("templates.breadcrumbBuilder")}
            </button>
            <span className="text-muted-foreground text-sm">/</span>
            <span className="text-sm font-medium">{t("templates.title")}</span>
          </div>
          <h1 className="text-2xl font-bold">{t("templates.title")}</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {t("templates.subtitle")}
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="border rounded-lg p-4 space-y-2">
              <Skeleton className="h-5 w-20 rounded-full" />
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ))}
        </div>
      ) : templates.length === 0 ? (
        <div className="border-2 border-dashed rounded-xl p-12 text-center">
          <p className="text-muted-foreground">{t("templates.noTemplates")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
          {templates.map((template) => (
            <TemplateCard
              key={template.id}
              template={template}
              onClick={() => router.push(`/builder/templates/${template.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
