import { useTranslations } from "next-intl";

/**
 * Extracts the template translation key from a catalog model ID.
 * Official templates have IDs like "official_ad_campaign_budget" ->
 * the translation key is "ad_campaign_budget".
 * Community or unknown IDs are returned as-is (will gracefully fallback).
 */
function toTemplateKey(catalogId: string): string {
  return catalogId.startsWith("official_")
    ? catalogId.slice("official_".length)
    : catalogId;
}

export function useTemplateTranslation(catalogId: string) {
  const tt = useTranslations("templates");
  const key = toTemplateKey(catalogId);

  return {
    displayName: (fallback: string) =>
      tt.has(`${key}.displayName`)
        ? tt(`${key}.displayName`)
        : fallback,
    shortDescription: (fallback: string) =>
      tt.has(`${key}.shortDescription`)
        ? tt(`${key}.shortDescription`)
        : fallback,
    description: (fallback: string) =>
      tt.has(`${key}.description`)
        ? tt(`${key}.description`)
        : fallback,
    scenarioDescription: (fallback: string) =>
      tt.has(`${key}.scenarioDescription`)
        ? tt(`${key}.scenarioDescription`)
        : fallback,
    categoryDisplayName: (fallback: string) =>
      tt.has(`${key}.categoryDisplayName`)
        ? tt(`${key}.categoryDisplayName`)
        : fallback,
  };
}

export function useCategoryTranslation() {
  const tt = useTranslations("templates");

  return {
    categoryName: (categoryKey: string, fallback: string) =>
      tt.has(`_categories.${categoryKey}`)
        ? tt(`_categories.${categoryKey}`)
        : fallback,
  };
}
