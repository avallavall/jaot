"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDialog } from "@/components/ui/dialog-custom";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Skeleton } from "@/components/ui/skeleton";

const CATEGORY_ICONS: Record<string, string> = {
  finance: "\u{1F4B0}",
  logistics: "\u{1F69A}",
  manufacturing: "\u{1F3ED}",
  agriculture: "\u{1F33E}",
  healthcare: "\u{1F3E5}",
  energy: "\u{26A1}",
  retail: "\u{1F6D2}",
  hr: "\u{1F465}",
  general: "\u{2699}\u{FE0F}",
  supply_chain: "\u{1F4E6}",
  facility_location: "\u{1F4CD}",
  network_graph: "\u{1F310}",
  cutting_packing: "\u{2702}\u{FE0F}",
  telecom: "\u{1F4F6}",
  transportation: "\u{1F680}",
  environmental: "\u{1F33F}",
  sports: "\u{1F3C6}",
  education: "\u{1F393}",
  real_estate: "\u{1F3E0}",
  mining: "\u{26CF}\u{FE0F}",
  water_management: "\u{1F4A7}",
  aerospace: "\u{1F6F0}\u{FE0F}",
  pharmaceutical: "\u{1F48A}",
  chemical_engineering: "\u{1F9EA}",
  forestry: "\u{1F332}",
  maritime: "\u{2693}",
  railway: "\u{1F682}",
  food_beverage: "\u{1F372}",
  textile: "\u{1F9F5}",
  construction: "\u{1F3D7}\u{FE0F}",
  advertising_media: "\u{1F4E3}",
  warehouse: "\u{1F3E2}",
  insurance: "\u{1F4CB}",
  government: "\u{1F3DB}\u{FE0F}",
};

const FALLBACK_CATEGORIES = [
  { id: "finance", icon: "\u{1F4B0}" },
  { id: "logistics", icon: "\u{1F69A}" },
  { id: "manufacturing", icon: "\u{1F3ED}" },
  { id: "agriculture", icon: "\u{1F33E}" },
  { id: "healthcare", icon: "\u{1F3E5}" },
  { id: "hr", icon: "\u{1F465}" },
  { id: "general", icon: "\u{2699}\u{FE0F}" },
];

const FALLBACK_GENERATOR_TYPES = [
  "budget_allocation",
  "knapsack",
  "assignment",
  "production_planning",
  "diet_optimization",
  "custom",
];

function formatDisplayName(id: string): string {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function CreatePageInner() {
  const t = useTranslations("solve.create");
  const { categoryLabel } = useCommonLabels();
  const router = useRouter();
  const dialog = useDialog();
  const searchParams = useSearchParams();

  // Dynamic metadata from API
  const [categories, setCategories] = useState(FALLBACK_CATEGORIES);
  const [generatorTypes, setGeneratorTypes] = useState(FALLBACK_GENERATOR_TYPES);
  const [categoryGenerators, setCategoryGenerators] = useState<Record<string, string[]>>({});

  // Read URL params — accept any value since backend validates on submit
  const rawCategory = searchParams.get("category") || "general";
  const rawGenerator = searchParams.get("generator") || FALLBACK_GENERATOR_TYPES[0];

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(rawCategory);
  const [generatorType, setGeneratorType] = useState(rawGenerator);
  const [creating, setCreating] = useState(false);

  // Fetch metadata from API on mount
  useEffect(() => {
    api
      .request<{
        categories: string[];
        generator_types: string[];
        category_generators: Record<string, string[]>;
      }>("/api/v2/solve/metadata")
      .then((data) => {
        setCategories(
          data.categories.map((id) => ({
            id,
            icon: CATEGORY_ICONS[id] || "\u{2699}\u{FE0F}",
          }))
        );
        setGeneratorTypes(data.generator_types);
        if (data.category_generators) {
          setCategoryGenerators(data.category_generators);
        }
      })
      .catch(() => {
        // Keep fallback values on error
      });
  }, []);

  // Sync category and generator to URL via replaceState
  const syncCreateUrl = useCallback(
    (cat: string, gen: string) => {
      const params = new URLSearchParams();
      if (cat !== "general") params.set("category", cat);
      if (gen !== generatorTypes[0]) params.set("generator", gen);
      const qs = params.toString();
      const url = qs
        ? `${window.location.pathname}?${qs}`
        : window.location.pathname;
      window.history.replaceState(null, "", url);
    },
    [generatorTypes]
  );

  const handleCategoryChange = (catId: string) => {
    setCategory(catId);
    const mapped = categoryGenerators[catId];
    const allowed =
      mapped && mapped.length > 0
        ? new Set([...mapped, "generic"])
        : null;
    if (allowed && !allowed.has(generatorType)) {
      const firstAvailable =
        generatorTypes.find((g) => allowed.has(g)) || generatorTypes[0];
      setGeneratorType(firstAvailable);
      syncCreateUrl(catId, firstAvailable);
    } else {
      syncCreateUrl(catId, generatorType);
    }
  };

  const handleGeneratorChange = (gen: string) => {
    setGeneratorType(gen);
    syncCreateUrl(category, gen);
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      dialog.showError(t("enterName"));
      return;
    }

    setCreating(true);
    try {
      const result = await api.createModel({
        name: name.trim(),
        description: description.trim(),
        category,
        generator_type: generatorType,
        input_schema: {},
        input_fields: [],
        example_input: {},
        tags: [],
      });

      dialog.showSuccess(t("createdSuccess"));
      setTimeout(() => router.push(`/solve/${result.id}`), 1000);
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedToCreate")));
    } finally {
      setCreating(false);
    }
  };

  /** Try page-specific i18n key, fall back to shared hook */
  const pageCategoryLabel = (id: string) => {
    const key = `categories.${id}`;
    return t.has(key) ? t(key) : categoryLabel(id);
  };

  /** Try i18n key, fall back to formatted id */
  const generatorLabel = (gen: string) => {
    const key = `generators.${gen}`;
    const translated = t.has(key) ? t(key) : null;
    return translated || formatDisplayName(gen);
  };

  /** Try i18n description key, fall back to empty */
  const generatorDesc = (gen: string) => {
    const key = `generators.${gen}Desc`;
    return t.has(key) ? t(key) : "";
  };

  // Filter generators by selected category mapping
  const filteredGenerators = (() => {
    const mapped = categoryGenerators[category];
    if (!mapped || mapped.length === 0) {
      // No mapping for this category -- show all generators
      return generatorTypes;
    }
    // Filter to mapped generators, always include 'generic'
    const allowed = new Set(mapped);
    allowed.add("generic");
    return generatorTypes.filter((g) => allowed.has(g));
  })();

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      <div className="mb-8">
        <Link
          href="/solve"
          className="text-sm text-muted-foreground hover:text-foreground mb-2 inline-block"
        >
          ← {t("backToModels")}
        </Link>
        <h1 className="text-3xl font-bold text-foreground mb-2">
          {t("title")}
        </h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <div className="space-y-6">
        <div>
          <label
            htmlFor="create-model-name"
            className="block text-sm font-medium mb-2"
          >
            {t("modelName")}
          </label>
          <Input
            id="create-model-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("modelNamePlaceholder")}
            className="w-full"
          />
        </div>

        <div>
          <label
            htmlFor="create-model-description"
            className="block text-sm font-medium mb-2"
          >
            {t("descriptionLabel")}
          </label>
          <textarea
            id="create-model-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("descriptionPlaceholder")}
            className="w-full px-3 py-2 rounded-md border bg-background text-sm min-h-[100px]"
          />
        </div>

        <div>
          <label
            className="block text-sm font-medium mb-2"
            id="create-model-category-label"
          >
            {t("categoryLabel")}
          </label>
          <div
            className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2"
            role="group"
            aria-labelledby="create-model-category-label"
          >
            {categories.map((cat) => (
              <button
                key={cat.id}
                onClick={() => handleCategoryChange(cat.id)}
                className={`p-3 rounded-lg border text-center transition-colors ${
                  category === cat.id
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <div className="text-xl mb-1">{cat.icon}</div>
                <div className="text-xs truncate">{pageCategoryLabel(cat.id)}</div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            className="block text-sm font-medium mb-2"
            id="create-model-problem-type-label"
          >
            {t("problemType")}
          </label>
          <div
            className="space-y-2"
            role="group"
            aria-labelledby="create-model-problem-type-label"
          >
            {filteredGenerators.map((gen) => (
              <button
                key={gen}
                onClick={() => handleGeneratorChange(gen)}
                className={`w-full p-4 rounded-lg border text-left transition-colors ${
                  generatorType === gen
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <div className="font-medium">{generatorLabel(gen)}</div>
                {generatorDesc(gen) && (
                  <div className="text-sm text-muted-foreground">
                    {generatorDesc(gen)}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="flex gap-3 pt-4">
          <Button variant="outline" onClick={() => router.push("/solve")}>
            {t("cancel")}
          </Button>
          <Button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
          >
            {creating ? t("creating") : t("createModel")}
          </Button>
        </div>
      </div>

      <dialog.DialogComponent />
    </div>
  );
}

export default function CreatePage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto px-4 py-8 max-w-2xl">
          <div className="mb-8">
            <Skeleton className="h-4 w-24 mb-2" />
            <Skeleton className="h-9 w-64 mb-2" />
            <Skeleton className="h-5 w-96" />
          </div>
          <div className="space-y-6">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-24 w-full" />
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2">
              {Array.from({ length: 7 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          </div>
        </div>
      }
    >
      <CreatePageInner />
    </Suspense>
  );
}
