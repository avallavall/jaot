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
 * categories, execution statuses, and transaction types.
 *
 * Uses `common.*` namespace with a consistent title-case fallback
 * when a key is missing from the locale file.
 */
export function useCommonLabels() {
  const tc = useTranslations("common");

  return {
    categoryLabel: (category: string): string =>
      tc.has(`categories.${category}`)
        ? tc(`categories.${category}`)
        : titleCase(category),

    statusLabel: (status: string): string =>
      tc.has(`executionStatus.${status}`)
        ? tc(`executionStatus.${status}`)
        : titleCase(status),

    transactionTypeLabel: (type: string): string =>
      tc.has(`transactionTypes.${type}`)
        ? tc(`transactionTypes.${type}`)
        : titleCase(type),
  };
}
