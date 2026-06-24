"use client";

import { useState, useEffect } from "react";
import { useDebounce } from "@/hooks/useDebounce";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api, OrganizationModel } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDialog } from "@/components/ui/dialog-custom";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { Coins, Truck, Factory, Wheat, Hospital, Users, Settings, Code, Star, Upload, Trash2, Package, MoreHorizontal, Clock, FileUp } from "lucide-react";
import { EmptyState } from "@/components/guidance/EmptyState";
import { FileImportDialog } from "@/components/solve/FileImportDialog";

export default function MyModelsPage() {
  const t = useTranslations("solve.list");
  const router = useRouter();
  const dialog = useDialog();
  const [models, setModels] = useState<OrganizationModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const debouncedSearch = useDebounce(search, 300);

  useEffect(() => {
    loadModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  const loadModels = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getMyModels({
        is_active: true,
        search: debouncedSearch || undefined,
      });
      setModels(result.items);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const handleToggleFavorite = async (model: OrganizationModel) => {
    // Optimistic: flip the star immediately
    const previousModels = models;
    setModels((prev) =>
      prev.map((m) =>
        m.id === model.id ? { ...m, is_favorite: !m.is_favorite } : m
      )
    );
    try {
      await api.updateMyModel(model.id, {
        is_favorite: !model.is_favorite,
      });
    } catch {
      // Revert on failure
      setModels(previousModels);
      dialog.showError(t("favoriteError"));
    }
  };

  const handleDeactivate = async (model: OrganizationModel) => {
    dialog.confirmCallback(
      t("confirmDeactivateMessage", { name: model.display_name || model.custom_name || "" }),
      async () => {
        try {
          await api.deactivateMyModel(model.id);
          dialog.showSuccess(t("modelDeactivated"));
          loadModels();
        } catch (err) {
          dialog.showError(getErrorMessage(err, t("failedToDeactivate")));
        }
      },
      t("confirmDeactivation")
    );
  };

  const handlePublish = (model: OrganizationModel) => {
    router.push(`/solve/${model.id}/publish`);
  };

  // Separate favorites and regular models
  const favorites = models.filter((s) => s.is_favorite);
  const regular = models.filter((s) => !s.is_favorite);

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">{t("title")}</h1>
          <p className="text-muted-foreground">
            {t("subtitle")}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setImportDialogOpen(true)}>
            <FileUp className="h-4 w-4 mr-1.5" />
            {t("importFile")}
          </Button>
          <Button variant="outline" onClick={() => router.push("/solve/create")}>
            {t("createCustom")}
          </Button>
          <Button onClick={() => router.push("/marketplace")}>
            {t("browseCatalog")}
          </Button>
        </div>
      </div>

      <div className="flex gap-2 mb-6">
        <Input
          type="text"
          placeholder={t("searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-md"
        />
      </div>

      {error && (
        <div className="mb-6 p-4 bg-destructive/10 text-destructive rounded-lg">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      )}

      {!loading && models.length === 0 && (
        <EmptyState
          icon={<Package className="h-12 w-12" />}
          title={t("noModels")}
          description={t("noModelsDescription")}
          expertDescription={t("noModelsExpert")}
          actionLabel={t("createWithAI")}
          actionHref="/builder/ai-assistant"
          secondaryActionLabel={t("browseCatalogAction")}
          secondaryActionHref="/marketplace"
          skillLevelCTAs={{
            beginner: {
              actionLabel: t("browseTemplates"),
              actionHref: "/builder/templates",
              secondaryActions: [
                { label: t("createWithAI"), href: "/builder/ai-assistant" },
              ],
            },
            intermediate: {
              actionLabel: t("createWithAI"),
              actionHref: "/builder/ai-assistant",
              secondaryActions: [
                { label: t("browseTemplates"), href: "/builder/templates" },
                { label: t("blankCanvas"), href: "/builder/new" },
              ],
            },
            expert: {
              actionLabel: t("blankCanvas"),
              actionHref: "/builder/new",
              secondaryActions: [
                { label: t("createWithAI"), href: "/builder/ai-assistant" },
              ],
            },
          }}
        />
      )}

      {!loading && favorites.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            {t("favorites")}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {favorites.map((model) => (
              <ModelCard
                key={model.id}
                model={model}
                t={t}
                onClick={() => router.push(`/solve/${model.id}`)}
                onRun={() => router.push(`/solve/${model.id}`)}
                onToggleFavorite={() => handleToggleFavorite(model)}
                onDeactivate={() => handleDeactivate(model)}
                onViewHistory={() => router.push(`/solve/${model.id}/history`)}
                onPublish={() => handlePublish(model)}
              />
            ))}
          </div>
        </div>
      )}

      {!loading && regular.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-4">
            {favorites.length > 0 ? t("otherModels") : t("allModels")}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {regular.map((model) => (
              <ModelCard
                key={model.id}
                model={model}
                t={t}
                onClick={() => router.push(`/solve/${model.id}`)}
                onRun={() => router.push(`/solve/${model.id}`)}
                onToggleFavorite={() => handleToggleFavorite(model)}
                onDeactivate={() => handleDeactivate(model)}
                onViewHistory={() => router.push(`/solve/${model.id}/history`)}
                onPublish={() => handlePublish(model)}
              />
            ))}
          </div>
        </div>
      )}

      <dialog.DialogComponent />

      <FileImportDialog open={importDialogOpen} onOpenChange={setImportDialogOpen} />
    </div>
  );
}

function ModelCard({
  model,
  t,
  onClick,
  onRun,
  onToggleFavorite,
  onDeactivate,
  onViewHistory,
  onPublish,
}: {
  model: OrganizationModel;
  t: ReturnType<typeof useTranslations>;
  onClick: () => void;
  onRun: () => void;
  onToggleFavorite: () => void;
  onDeactivate: () => void;
  onViewHistory: () => void;
  onPublish?: () => void;
}) {
  const categoryIcons: Record<string, React.ReactNode> = {
    finance: <Coins className="w-5 h-5" />,
    logistics: <Truck className="w-5 h-5" />,
    manufacturing: <Factory className="w-5 h-5" />,
    agriculture: <Wheat className="w-5 h-5" />,
    healthcare: <Hospital className="w-5 h-5" />,
    hr: <Users className="w-5 h-5" />,
    general: <Settings className="w-5 h-5" />,
  };

  return (
    <div className="bg-card border rounded-lg p-5 hover:shadow-md transition-shadow cursor-pointer" onClick={onClick}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-primary">{categoryIcons[model.category || ""] || <Code className="w-5 h-5" />}</span>
          <div>
            <h3 className="font-semibold">{model.display_name}</h3>
            {!!(model as unknown as Record<string, unknown>).is_official && (
              <span className="text-xs text-blue-600">Official</span>
            )}
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onToggleFavorite(); }}
          className="hover:scale-110 transition-transform text-primary"
          aria-label={model.is_favorite ? t("removeFavorite") : t("addFavorite")}
        >
          <Star className={`w-5 h-5 ${model.is_favorite ? "fill-current" : ""}`} />
        </button>
      </div>

      {model.description && (
        <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
          {model.description}
        </p>
      )}

      <div className="flex items-center gap-4 text-xs text-muted-foreground mb-4">
        <span>{t("runs", { count: model.total_executions })}</span>
        <span>{t("creditsUsed", { count: model.total_credits_used })}</span>
      </div>

      {model.last_executed_at && (
        <div className="text-xs text-muted-foreground mb-4">
          {t("lastRun", { date: new Date(model.last_executed_at).toLocaleDateString() })}
        </div>
      )}

      <div className="flex items-center justify-between pt-3 border-t">
        <div className="text-sm">
          <CreditsCostLabel model={model} t={t} />
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0 text-muted-foreground"
                aria-label={t("moreActions")}
                onClick={(e) => e.stopPropagation()}
              >
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={onViewHistory}>
                <Clock className="w-4 h-4 mr-2" />
                {t("history")}
              </DropdownMenuItem>
              {onPublish && (
                <DropdownMenuItem onClick={onPublish}>
                  <Upload className="w-4 h-4 mr-2" />
                  {model.catalog_id ? t("updateListing") : t("publishToMarketplace")}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onClick={onDeactivate}
              >
                <Trash2 className="w-4 h-4 mr-2" />
                {t("deactivateModel")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" onClick={(e) => { e.stopPropagation(); onRun(); }}>
            {t("run")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function CreditsCostLabel({
  model,
  t,
}: {
  model: OrganizationModel;
  t: ReturnType<typeof useTranslations>;
}) {
  // Fixed price per execution
  if (model.credits_per_execution > 0) {
    return (
      <span className="text-muted-foreground text-xs">
        {t("creditsPerRun", { credits: model.credits_per_execution })}
      </span>
    );
  }

  // Dynamic pricing: show average if we have execution history
  if (model.total_executions > 0 && model.total_credits_used > 0) {
    const avg = Math.round(model.total_credits_used / model.total_executions);
    return (
      <span className="text-muted-foreground text-xs">
        {t("avgCreditsPerRun", { avg })}
      </span>
    );
  }

  // Dynamic pricing: no history yet, show label + tooltip
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground text-xs">
      {t("dynamicCredits")}
      <HelpTooltip content={t("dynamicCreditsTooltip")} side="top" size={12} />
    </span>
  );
}
