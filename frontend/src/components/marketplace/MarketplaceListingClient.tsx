"use client";

import { useEffect, useState, Suspense, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useDebounce } from "@/hooks/useDebounce";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Filter, X } from "lucide-react";
import { api } from "@/lib/api";
import type { ModelCatalogItem, PaginatedResponse } from "@/lib/types";
import { useUrlFilters } from "@/hooks/useUrlFilters";
import { useAuth } from "@/contexts/AuthContext";
import { useDialog } from "@/components/ui/dialog-custom";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { FeaturedCarousel } from "@/components/marketplace/FeaturedCarousel";
import { MarketplaceModelCard } from "@/components/marketplace/MarketplaceModelCard";
import {
  CarouselSkeleton,
  ModelGridSkeleton,
} from "@/components/marketplace/MarketplaceSkeletons";
import { SearchAutocomplete } from "@/components/marketplace/SearchAutocomplete";
import { FilterSidebar } from "@/components/marketplace/FilterSidebar";

function MarketplaceListingInner() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const t = useTranslations("marketplace");
  const tCatalog = useTranslations("marketplace.catalog");
  const dialog = useDialog();

  const [models, setModels] = useState<ModelCatalogItem[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showMobileFilters, setShowMobileFilters] = useState(false);

  // Auth-only state: favorites
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

  // URL-persisted filters
  const { filters, updateFilter, clearFilters, activeFilterCount } =
    useUrlFilters();

  // Local search input with debounce for responsive typing
  const [searchInput, setSearchInput] = useState(filters.search);
  const debouncedSearch = useDebounce(searchInput, 300);

  // Sync debounced search to URL filters
  useEffect(() => {
    if (debouncedSearch !== filters.search) {
      updateFilter("search", debouncedSearch);
    }
  }, [debouncedSearch]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reverse sync: when filters.search changes externally, sync back to input
  useEffect(() => {
    setSearchInput(filters.search);
  }, [filters.search]);

  // Load user's favorites (auth only)
  const loadAuthData = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const favs = (await api.request("/api/v2/models/favorites")) as {
        items: { id: string }[];
      };
      setFavorites(new Set(favs.items.map((f) => f.id)));
    } catch {
      // Graceful degradation: auth data unavailable → render unauthenticated state.
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (!authLoading) {
      loadAuthData();
    }
  }, [authLoading, loadAuthData]);

  // Reload models when any filter changes
  useEffect(() => {
    loadModels();
  }, [debouncedSearch, filters.category, filters.sort, filters.official, filters.minRating, filters.page]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadModels = async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number> = { page_size: 12 };
      if (debouncedSearch) params.search = debouncedSearch;
      if (filters.category) params.category = filters.category;
      if (filters.sort && filters.sort !== "popular")
        params.sort_by = filters.sort;
      if (filters.official) params.is_official = 1;
      if (filters.minRating !== null) params.min_rating = filters.minRating;
      if (filters.page > 1) params.page = filters.page;

      const queryString = new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)])
      ).toString();
      const data = (await api.request(
        `/api/v2/models/catalog?${queryString}`
      )) as PaginatedResponse<ModelCatalogItem>;
      setModels(data.items || []);
      setTotalCount(data.total || 0);
      setTotalPages(data.total_pages || Math.ceil((data.total || 0) / 12));
    } catch (err) {
      setError(getErrorMessage(err, t("noResults")));
    } finally {
      setLoading(false);
    }
  };

  // Featured models: is_featured, fallback to top 5 by rating
  const featuredModels = useMemo(() => {
    const featured = models.filter((m) => m.is_featured);
    if (featured.length > 0) return featured.slice(0, 5);
    // Fallback: top 5 by rating
    return [...models]
      .filter((m) => m.avg_rating != null && m.avg_rating > 0)
      .sort((a, b) => (b.avg_rating ?? 0) - (a.avg_rating ?? 0))
      .slice(0, 5);
  }, [models]);

  // Extract unique categories from loaded models
  const availableCategories = useMemo(() => {
    const cats = new Set(models.map((m) => m.category));
    return Array.from(cats).sort();
  }, [models]);

  // Auth-only: seed a fork ModelProject and open it in the studio (P1.5 fusion —
  // THE way to use a marketplace model; the legacy activate flow is gone).
  const handleUseInStudio = async (model: ModelCatalogItem) => {
    try {
      const project = await api.createProjectFromMarketplace(model.id);
      router.push(`/studio/${project.id}/build`);
    } catch (err) {
      const status = getErrorStatus(err);
      dialog.showError(
        status === 422
          ? tCatalog("useInStudioUnavailable")
          : getErrorMessage(err, tCatalog("useInStudioFailed"))
      );
    }
  };

  // Auth-only: toggle favorite
  const toggleFavorite = async (modelId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const isFav = favorites.has(modelId);
    try {
      if (isFav) {
        await api.request(`/api/v2/models/favorites/${modelId}`, { method: "DELETE" });
        setFavorites((prev) => {
          const next = new Set(prev);
          next.delete(modelId);
          return next;
        });
      } else {
        await api.request(`/api/v2/models/favorites/${modelId}`, { method: "POST" });
        setFavorites((prev) => new Set(prev).add(modelId));
      }
    } catch {
      dialog.showError(tCatalog("failedToUpdateFavorite"));
    }
  };

  return (
    <div className="space-y-8">
      {/* Hero Carousel - featured or top-rated models */}
      {loading ? (
        <CarouselSkeleton />
      ) : (
        <FeaturedCarousel models={featuredModels} />
      )}

      {error && (
        <div className="mx-4 p-4 bg-destructive/10 text-destructive rounded-lg">
          {error}
        </div>
      )}

      {/* Main content: sidebar + grid */}
      <div className="flex gap-6">
        {/* Left sidebar - desktop visible, mobile hidden */}
        <aside className="hidden lg:block w-64 flex-shrink-0">
          <FilterSidebar
            filters={filters}
            updateFilter={updateFilter}
            clearFilters={clearFilters}
            activeFilterCount={activeFilterCount}
            categories={availableCategories}
          />
        </aside>

        <div className="flex-1 min-w-0">
          <div className="flex gap-2 mb-6">
            <SearchAutocomplete
              value={searchInput}
              onChange={setSearchInput}
              onCategorySelect={(cat) => updateFilter("category", cat)}
              placeholder={t("searchPlaceholder")}
            />
            {/* Mobile filter button (lg:hidden) */}
            <Button
              variant="outline"
              className="lg:hidden flex-shrink-0 h-12"
              onClick={() => setShowMobileFilters(true)}
            >
              <Filter className="w-4 h-4" />
              {activeFilterCount > 0 && (
                <Badge variant="secondary" className="ml-1 px-1.5 py-0.5 text-xs">
                  {activeFilterCount}
                </Badge>
              )}
            </Button>
          </div>

          {activeFilterCount > 0 && (
            <div className="flex items-center gap-2 mb-4 text-sm text-muted-foreground">
              <span>
                {t("filters.activeCount", { count: activeFilterCount })}
              </span>
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={clearFilters}
              >
                {t("filters.clearAll")}
              </Button>
            </div>
          )}

          <div className="mb-4">
            <h2 className="text-xl font-semibold">
              {t("allModels")}{" "}
              <span className="text-muted-foreground font-normal">
                ({totalCount})
              </span>
            </h2>
          </div>

          {loading ? (
            <ModelGridSkeleton />
          ) : models.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-lg mb-2">{t("noResults")}</p>
              {activeFilterCount > 0 && (
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  {t("filters.clearAll")}
                </Button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {models.map((model) => (
                <MarketplaceModelCard
                  key={model.id}
                  model={model}
                  isAuthenticated={isAuthenticated}
                  isFavorite={favorites.has(model.id)}
                  onToggleFavorite={(e) => toggleFavorite(model.id, e)}
                  onUseInStudio={() => handleUseInStudio(model)}
                />
              ))}
            </div>
          )}

          {!loading && totalPages > 1 && (
            <div className="flex justify-center gap-2 mt-8">
              <Button
                variant="outline"
                disabled={filters.page === 1}
                onClick={() => updateFilter("page", filters.page - 1)}
              >
                {tCatalog("previous")}
              </Button>
              <span className="px-4 py-2 text-sm">
                {tCatalog("pageOf", { page: filters.page, totalPages })}
              </span>
              <Button
                variant="outline"
                disabled={filters.page === totalPages}
                onClick={() => updateFilter("page", filters.page + 1)}
              >
                {tCatalog("next")}
              </Button>
            </div>
          )}
        </div>
      </div>

      {showMobileFilters && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-40"
            onClick={() => setShowMobileFilters(false)}
          />
          <div className="fixed inset-y-0 left-0 w-80 bg-background z-50 overflow-y-auto p-6 shadow-xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold">
                {t("filters.title")}
              </h2>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowMobileFilters(false)}
              >
                <X className="w-5 h-5" />
                <span className="sr-only">{t("filters.closeFilters")}</span>
              </Button>
            </div>
            <FilterSidebar
              filters={filters}
              updateFilter={updateFilter}
              clearFilters={clearFilters}
              activeFilterCount={activeFilterCount}
              categories={availableCategories}
            />
          </div>
        </>
      )}

      <dialog.DialogComponent />
    </div>
  );
}

export function MarketplaceListingClient() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-12" aria-busy="true">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      }
    >
      <MarketplaceListingInner />
    </Suspense>
  );
}
