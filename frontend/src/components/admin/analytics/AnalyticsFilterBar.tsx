"use client";

import { useTranslations } from "next-intl";
import type { AnalyticsFilters } from "./analytics-types";
import { EVENT_TYPES, formatEventType } from "./analytics-helpers";

const DOMAINS = [
  "Solver",
  "AI Builder",
  "Marketplace",
  "MCP",
  "Scheduling",
];

interface AnalyticsFilterBarProps {
  filters: AnalyticsFilters;
  onFiltersChange: (filters: AnalyticsFilters) => void;
  countryOptions: string[];
}

const selectClass =
  "h-9 rounded-md border border-input bg-background px-3 text-sm " +
  "text-foreground focus:outline-none focus:ring-2 focus:ring-ring";

export function AnalyticsFilterBar({
  filters,
  onFiltersChange,
  countryOptions,
}: AnalyticsFilterBarProps) {
  const t = useTranslations("admin.featureAnalytics");
  const hasFilters =
    filters.eventType || filters.countryCode || filters.domain;

  function update(patch: Partial<AnalyticsFilters>) {
    onFiltersChange({ ...filters, ...patch });
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <select
        value={filters.eventType ?? ""}
        onChange={(e) =>
          update({ eventType: e.target.value || null })
        }
        className={selectClass}
      >
        <option value="">{t("allEventTypes")}</option>
        {EVENT_TYPES.map((et) => (
          <option key={et} value={et}>
            {formatEventType(et, t)}
          </option>
        ))}
      </select>

      <select
        value={filters.domain ?? ""}
        onChange={(e) =>
          update({ domain: e.target.value || null })
        }
        className={selectClass}
      >
        <option value="">{t("allDomains")}</option>
        {DOMAINS.map((d) => (
          <option key={d} value={d}>
            {t.has(`domains.${d}`) ? t(`domains.${d}`) : d}
          </option>
        ))}
      </select>

      <select
        value={filters.countryCode ?? ""}
        onChange={(e) =>
          update({ countryCode: e.target.value || null })
        }
        className={selectClass}
      >
        <option value="">{t("allCountries")}</option>
        {countryOptions.map((cc) => (
          <option key={cc} value={cc}>
            {cc}
          </option>
        ))}
      </select>

      <button
        onClick={() => update({ compare: !filters.compare })}
        className={`h-9 rounded-md border px-3 text-sm font-medium transition-colors ${
          filters.compare
            ? "border-primary bg-primary text-primary-foreground"
            : "border-input bg-background text-muted-foreground hover:text-foreground"
        }`}
      >
        {t("compare")}
      </button>

      {hasFilters && (
        <button
          onClick={() =>
            onFiltersChange({
              eventType: null,
              countryCode: null,
              domain: null,
              compare: filters.compare,
            })
          }
          className="h-9 rounded-md px-3 text-sm text-muted-foreground hover:text-foreground"
        >
          {t("clearFilters")}
        </button>
      )}
    </div>
  );
}
