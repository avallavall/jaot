"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import type { TemplateSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useTemplateTranslation, toTemplateKey } from "@/hooks/useTemplateTranslation";
import { getErrorMessage } from "@/lib/errors";

interface TemplateCardProps {
  template: TemplateSummary;
  onUse: () => void;
  busy: boolean;
}

function TemplateCard({ template, onUse, busy }: TemplateCardProps) {
  const t = useTranslations("studio");
  const tb = useTranslations("builder");
  const tmpl = useTemplateTranslation(template.id);
  const categoryKey = `templates.categories.${template.category}`;
  return (
    <div className="border rounded-lg p-4 bg-card hover:border-primary/50 hover:shadow-sm transition-all flex flex-col">
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
          {tb.has(categoryKey) ? tb(categoryKey) : template.category}
        </span>
      </div>
      <h3 className="font-semibold text-sm mt-2">{tmpl.displayName(template.display_name)}</h3>
      {template.description && (
        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
          {tmpl.description(template.description)}
        </p>
      )}
      <div className="mt-3 flex items-center justify-end">
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          disabled={busy}
          onClick={onUse}
          data-testid={`use-template-${template.id}`}
        >
          {t("useTemplate")}
        </Button>
      </div>
    </div>
  );
}

/**
 * Studio template gallery. Picking "Use" SEEDS a first-class ModelProject from the
 * template (server-side materialization + a v1 commit) and drops the user straight
 * into the workspace — the P2 centralization funnel, replacing the old "solve a
 * template once and lose it" flow.
 *
 * Source = the curated YAML templates (`listTemplates`), not the marketplace catalog:
 * every official template is guaranteed to materialize from its example input, so
 * every card's "Use" succeeds. Community marketplace models live behind the separate
 * "From marketplace" entry point.
 */
export default function StudioTemplatesPage() {
  const t = useTranslations("studio");
  const tt = useTranslations("templates");
  const tb = useTranslations("builder");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [creatingId, setCreatingId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .listTemplates()
      .then((res) => setTemplates(res.templates))
      .catch(() => setTemplates([]))
      .finally(() => setIsLoading(false));
  }, []);

  // Client-side search over what the user actually SEES: the localized name,
  // description and category (falling back to the raw English fields), so
  // "mochila" finds Knapsack on the es locale — plus the raw id for power users.
  const visibleTemplates = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter((tpl) => {
      const key = toTemplateKey(tpl.id);
      const name = tt.has(`${key}.displayName`) ? tt(`${key}.displayName`) : tpl.display_name;
      const desc = tt.has(`${key}.description`)
        ? tt(`${key}.description`)
        : (tpl.description ?? "");
      const categoryKey = `templates.categories.${tpl.category}`;
      const category = tb.has(categoryKey) ? tb(categoryKey) : tpl.category;
      return `${name} ${desc} ${category} ${tpl.display_name} ${tpl.id}`
        .toLowerCase()
        .includes(q);
    });
  }, [templates, query, tt, tb]);

  const handleUse = async (id: string) => {
    if (creatingId) return;
    setCreatingId(id);
    try {
      const project = await api.createProjectFromTemplate(id, activeWorkspaceId ?? undefined);
      router.push(`/studio/${project.id}/build`);
    } catch (err) {
      toast.error(getErrorMessage(err, t("createFailed")));
      setCreatingId(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t("templatesTitle")}</h1>
        <p className="text-muted-foreground text-sm mt-1">{t("templatesSubtitle")}</p>
      </div>

      <div className="relative mb-4 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("templatesSearchPlaceholder")}
          className="pl-9"
          data-testid="studio-templates-search"
        />
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
          <p className="text-muted-foreground">{t("templatesEmpty")}</p>
        </div>
      ) : visibleTemplates.length === 0 ? (
        <div
          className="border-2 border-dashed rounded-xl p-12 text-center"
          data-testid="studio-templates-no-matches"
        >
          <p className="text-muted-foreground">{t("templatesNoMatches", { query })}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visibleTemplates.map((tpl) => (
            <TemplateCard
              key={tpl.id}
              template={tpl}
              busy={creatingId !== null}
              onUse={() => handleUse(tpl.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
