"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RatingFilter } from "./RatingFilter";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import type { FilterDefaults } from "@/hooks/useUrlFilters";

interface FilterSidebarProps {
  filters: FilterDefaults;
  updateFilter: <K extends keyof FilterDefaults>(
    key: K,
    value: FilterDefaults[K]
  ) => void;
  clearFilters: () => void;
  activeFilterCount: number;
  categories: string[];
}

const SORT_OPTIONS = [
  { value: "popular", labelKey: "sortPopular" },
  { value: "rating", labelKey: "sortRating" },
  { value: "newest", labelKey: "sortNewest" },
] as const;

export function FilterSidebar({
  filters,
  updateFilter,
  clearFilters,
  activeFilterCount,
  categories,
}: FilterSidebarProps) {
  const t = useTranslations("marketplace.filters");
  const { categoryLabel } = useCommonLabels();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">{t("title")}</h3>
      </div>

      <div className="space-y-2">
        <h4 className="text-sm font-medium">{t("sort")}</h4>
        <Select
          value={filters.sort}
          onValueChange={(val) => updateFilter("sort", val)}
        >
          <SelectTrigger className="w-full" aria-label={t("sort")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {t(opt.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <h4 className="text-sm font-medium">{t("categories")}</h4>
        <div className="space-y-2">
          {categories.map((cat) => {
            const isChecked = filters.category === cat;
            const label = categoryLabel(cat);
            return (
              <label
                key={cat}
                className="flex items-center gap-2 text-sm cursor-pointer"
              >
                <Checkbox
                  checked={isChecked}
                  onCheckedChange={(checked) => {
                    updateFilter("category", checked ? cat : null);
                  }}
                />
                <span>{label}</span>
              </label>
            );
          })}
          {filters.category && (
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => updateFilter("category", null)}
            >
              {t("clearPrice")}
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-2">
        <h4 className="text-sm font-medium">{t("rating")}</h4>
        <RatingFilter
          value={filters.minRating}
          onChange={(val) => updateFilter("minRating", val)}
        />
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Checkbox
            checked={filters.official}
            onCheckedChange={(checked) =>
              updateFilter("official", checked === true)
            }
          />
          <span>{t("officialOnly")}</span>
        </label>
      </div>

      {activeFilterCount > 0 && (
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={clearFilters}
        >
          {t("clearAll")}
        </Button>
      )}
    </div>
  );
}
