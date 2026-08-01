import { useMemo } from "react";
import { useTranslations } from "next-intl";

/**
 * Format a snake_case string as Title Case.
 * "mixed_integer" → "Mixed Integer"
 */
function titleCase(value: string): string {
  return value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * Shared translation helpers for enum-like values that appear across many pages:
 * categories and execution statuses.
 *
 * Uses `common.*` namespace with a consistent title-case fallback
 * when a key is missing from the locale file.
 */
export function useCommonLabels() {
  const tc = useTranslations("common");

  // Memoized so callers can list these in a useMemo dependency array and still get
  // the memo they asked for — a fresh object each render would re-derive every time.
  return useMemo(
    () => ({
      categoryLabel: (category: string): string =>
        tc.has(`categories.${category}`)
          ? tc(`categories.${category}`)
          : titleCase(category),

      statusLabel: (status: string): string =>
        tc.has(`executionStatus.${status}`)
          ? tc(`executionStatus.${status}`)
          : titleCase(status),
    }),
    [tc],
  );
}
