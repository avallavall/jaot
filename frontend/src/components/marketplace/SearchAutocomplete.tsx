"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Search, Package, Tag } from "lucide-react";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { ModelCatalogItem, PaginatedResponse } from "@/lib/types";
import { useDebounce } from "@/hooks/useDebounce";

// Known categories for client-side matching
const KNOWN_CATEGORIES = [
  "linear",
  "integer",
  "mixed_integer",
  "nonlinear",
  "quadratic",
  "network",
  "scheduling",
  "routing",
  "assignment",
  "other",
] as const;

interface SearchAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  onCategorySelect?: (category: string) => void;
}

export function SearchAutocomplete({
  value,
  onChange,
  placeholder,
  onCategorySelect,
}: SearchAutocompleteProps) {
  const t = useTranslations("marketplace.search");
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const [suggestions, setSuggestions] = useState<ModelCatalogItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);

  const debouncedValue = useDebounce(value, 300);

  // Fetch model suggestions when debounced value changes
  useEffect(() => {
    if (!debouncedValue || debouncedValue.length < 2) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const data = (await api.request(
          `/api/v2/models/catalog?search=${encodeURIComponent(debouncedValue)}&page_size=5`
        )) as PaginatedResponse<ModelCatalogItem>;
        if (!cancelled) {
          setSuggestions(data.items || []);
          setShowDropdown(true);
          setSelectedIndex(-1);
        }
      } catch {
        if (!cancelled) {
          setSuggestions([]);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [debouncedValue]);

  // Match categories client-side (memoized to stabilize useCallback deps)
  const matchingCategories = useMemo(
    () =>
      value.length >= 2
        ? KNOWN_CATEGORIES.filter((cat) =>
            cat.toLowerCase().includes(value.toLowerCase())
          )
        : [],
    [value]
  );

  // Total items for keyboard navigation
  const totalItems = suggestions.length + matchingCategories.length;

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = useCallback(
    (index: number) => {
      if (index < suggestions.length) {
        // Model selected
        const model = suggestions[index];
        setShowDropdown(false);
        router.push(`/marketplace/${model.id}`);
      } else {
        // Category selected
        const catIndex = index - suggestions.length;
        const category = matchingCategories[catIndex];
        setShowDropdown(false);
        onChange("");
        onCategorySelect?.(category);
      }
    },
    [suggestions, matchingCategories, router, onChange, onCategorySelect]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown || totalItems === 0) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev < totalItems - 1 ? prev + 1 : 0
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev > 0 ? prev - 1 : totalItems - 1
        );
        break;
      case "Enter":
        e.preventDefault();
        if (selectedIndex >= 0) {
          handleSelect(selectedIndex);
        }
        break;
      case "Escape":
        setShowDropdown(false);
        setSelectedIndex(-1);
        break;
    }
  };

  const hasResults = showDropdown && (suggestions.length > 0 || matchingCategories.length > 0);
  const hasNoResults = showDropdown && suggestions.length === 0 && matchingCategories.length === 0 && debouncedValue.length >= 2;

  return (
    <div ref={containerRef} className="relative flex-1">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
        <Input
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => {
            if (value.length >= 2 && (suggestions.length > 0 || matchingCategories.length > 0)) {
              setShowDropdown(true);
            }
          }}
          onKeyDown={handleKeyDown}
          className="pl-10 h-12 text-lg"
        />
      </div>

      {(hasResults || hasNoResults) && (
        <div
          data-testid="search-dropdown"
          className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-lg z-50 overflow-hidden max-h-80 overflow-y-auto"
        >
          {suggestions.length > 0 && (
            <div>
              <div className="px-3 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                {t("models")}
              </div>
              {suggestions.map((model, i) => (
                <button
                  key={model.id}
                  type="button"
                  className={`flex items-center gap-3 w-full px-3 py-2 text-left text-sm hover:bg-accent transition-colors ${
                    selectedIndex === i ? "bg-accent" : ""
                  }`}
                  onClick={() => handleSelect(i)}
                  onMouseEnter={() => setSelectedIndex(i)}
                >
                  {model.logo_url ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={model.logo_url}
                      alt=""
                      className="w-6 h-6 rounded object-cover flex-shrink-0"
                    />
                  ) : (
                    <Package className="w-6 h-6 text-muted-foreground flex-shrink-0" />
                  )}
                  <span className="truncate">{model.display_name}</span>
                </button>
              ))}
            </div>
          )}

          {matchingCategories.length > 0 && (
            <div>
              {suggestions.length > 0 && (
                <div className="border-t border-border" />
              )}
              <div className="px-3 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                {t("categories")}
              </div>
              {matchingCategories.map((cat, i) => {
                const globalIndex = suggestions.length + i;
                const label = cat
                  .split("_")
                  .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                  .join(" ");
                return (
                  <button
                    key={cat}
                    type="button"
                    className={`flex items-center gap-3 w-full px-3 py-2 text-left text-sm hover:bg-accent transition-colors ${
                      selectedIndex === globalIndex ? "bg-accent" : ""
                    }`}
                    onClick={() => handleSelect(globalIndex)}
                    onMouseEnter={() => setSelectedIndex(globalIndex)}
                  >
                    <Tag className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                    <span>{label}</span>
                  </button>
                );
              })}
            </div>
          )}

          {hasNoResults && (
            <div className="px-3 py-4 text-sm text-muted-foreground text-center">
              {t("noSuggestions")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
