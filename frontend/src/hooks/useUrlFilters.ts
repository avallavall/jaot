import { useSearchParams } from "next/navigation";
import { useState, useCallback, useEffect, useRef } from "react";

export interface FilterDefaults {
  category: string | null;
  search: string;
  sort: string;
  official: boolean;
  featured: boolean;
  page: number;
  minRating: number | null;
}

export const DEFAULTS: FilterDefaults = {
  category: null,
  search: "",
  sort: "popular",
  official: false,
  featured: false,
  page: 1,
  minRating: null,
};

export const VALID_SORTS = ["popular", "newest", "rating"] as const;

export function useUrlFilters() {
  const searchParams = useSearchParams();

  // Parse URL params with fallback to defaults for invalid values
  const parseFromUrl = useCallback((): FilterDefaults => {
    const rawSort = searchParams.get("sort") ?? "popular";
    const rawPage = parseInt(searchParams.get("page") ?? "1", 10);
    const rawMinRating = searchParams.get("minRating");
    return {
      category: searchParams.get("category") || null,
      search: searchParams.get("search") ?? "",
      sort: (VALID_SORTS as readonly string[]).includes(rawSort)
        ? rawSort
        : "popular",
      official: searchParams.get("official") === "true",
      featured: searchParams.get("featured") === "true",
      page: Number.isNaN(rawPage) || rawPage < 1 ? 1 : rawPage,
      minRating:
        rawMinRating !== null && rawMinRating !== ""
          ? Number(rawMinRating)
          : null,
    };
  }, [searchParams]);

  const [filters, setFilters] = useState<FilterDefaults>(parseFromUrl);

  // Track initial mount to avoid re-syncing URL -> state on first render
  const isInitialMount = useRef(true);
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    // URL changed externally (e.g., popstate from browser back/forward)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters(parseFromUrl());
  }, [searchParams, parseFromUrl]);

  // Write non-default values to URL via replaceState (shallow update, no _rsc request)
  const syncToUrl = useCallback((newFilters: FilterDefaults) => {
    const params = new URLSearchParams();
    if (newFilters.category) params.set("category", newFilters.category);
    if (newFilters.search) params.set("search", newFilters.search);
    if (newFilters.sort !== "popular") params.set("sort", newFilters.sort);
    if (newFilters.official) params.set("official", "true");
    if (newFilters.featured) params.set("featured", "true");
    if (newFilters.page > 1) params.set("page", String(newFilters.page));
    if (newFilters.minRating !== null)
      params.set("minRating", String(newFilters.minRating));

    const qs = params.toString();
    // Use window.location.pathname directly to avoid locale prefix issues
    // (see RESEARCH Pitfall 4 — usePathname from next-intl may strip locale)
    const pathname = window.location.pathname;
    const url = qs ? `${pathname}?${qs}` : pathname;
    window.history.replaceState(null, "", url);
  }, []);

  // Update a single filter and sync to URL
  const updateFilter = useCallback(
    <K extends keyof FilterDefaults>(key: K, value: FilterDefaults[K]) => {
      setFilters((prev) => {
        const next = { ...prev, [key]: value };
        // Reset page to 1 when any filter other than page changes
        if (key !== "page") next.page = 1;
        syncToUrl(next);
        return next;
      });
    },
    [syncToUrl]
  );

  // Clear all filters and reset URL to clean path
  const clearFilters = useCallback(() => {
    const defaults = { ...DEFAULTS };
    setFilters(defaults);
    syncToUrl(defaults);
  }, [syncToUrl]);

  // Count active (non-default) filters — page is navigation, not a "filter"
  const activeFilterCount =
    (filters.category !== null ? 1 : 0) +
    (filters.search !== "" ? 1 : 0) +
    (filters.sort !== "popular" ? 1 : 0) +
    (filters.official ? 1 : 0) +
    (filters.featured ? 1 : 0) +
    (filters.minRating !== null ? 1 : 0);

  return { filters, updateFilter, clearFilters, activeFilterCount };
}
