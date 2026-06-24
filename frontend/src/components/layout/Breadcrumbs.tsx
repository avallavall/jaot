"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { ChevronRight, Home } from "lucide-react";
import { routing } from "@/i18n/routing";

/**
 * Segment-to-translation-key mapping for human-readable breadcrumb names.
 * Falls back to capitalized raw segment if not found.
 */
const SEGMENT_KEYS: Record<string, string> = {
  solve: "breadcrumbs.solve",
  workspace: "breadcrumbs.workspace",
  marketplace: "breadcrumbs.marketplace",
  admin: "breadcrumbs.admin",
  triggers: "breadcrumbs.triggers",
  builder: "breadcrumbs.builder",
  catalog: "breadcrumbs.catalog",
  models: "breadcrumbs.models",
  profile: "breadcrumbs.profile",
  templates: "breadcrumbs.templates",
  audit: "breadcrumbs.audit",
  team: "breadcrumbs.team",
  settings: "breadcrumbs.settings",
  chat: "breadcrumbs.chat",
  workspaces: "breadcrumbs.workspaces",
  organizations: "breadcrumbs.organizations",
  users: "breadcrumbs.users",
  credits: "breadcrumbs.credits",
  executions: "breadcrumbs.executions",
  reviews: "breadcrumbs.reviews",
  favorites: "breadcrumbs.favorites",
  billing: "breadcrumbs.billing",
  invoices: "breadcrumbs.invoices",
  usage: "breadcrumbs.usage",
  "api-keys": "breadcrumbs.apiKeys",
  new: "breadcrumbs.new",
  "ai-assistant": "breadcrumbs.aiAssistant",
  "multi-objective": "breadcrumbs.multiObjective",
  analytics: "breadcrumbs.analytics",
  "seller-analytics": "breadcrumbs.sellerAnalytics",
  verification: "breadcrumbs.verification",
  promotions: "breadcrumbs.promotions",
  create: "breadcrumbs.create",
  custom: "breadcrumbs.custom",
  "my-profile": "breadcrumbs.myProfile",
  "seller-earnings": "breadcrumbs.sellerEarnings",
  docs: "breadcrumbs.docs",
  licenses: "breadcrumbs.licenses",
  history: "breadcrumbs.history",
};

/**
 * Auto-generating breadcrumb navigation from URL pathname.
 *
 * Returns null on root path ("/") and top-level pages (single segment like "/solve").
 * Renders accessible nav > ol > li structure with proper ARIA attributes.
 */
export function Breadcrumbs() {
  const pathname = usePathname();
  const locale = useLocale();
  const t = useTranslations("common");

  // Split, remove empty segments, and filter out the locale prefix
  const locales: readonly string[] = routing.locales;
  const allSegments = pathname.split("/").filter(Boolean);
  const segments = allSegments[0] && locales.includes(allSegments[0])
    ? allSegments.slice(1)
    : allSegments;

  // Return null for root or top-level pages (redundant with sidebar)
  if (segments.length <= 1) {
    return null;
  }

  const getLabel = (segment: string): string => {
    const key = SEGMENT_KEYS[segment];
    if (key) {
      return t(key);
    }
    return segment.charAt(0).toUpperCase() + segment.slice(1);
  };

  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <li className="flex items-center">
          <Link
            href="/"
            className="hover:text-foreground transition-colors"
            aria-label={t("breadcrumbs.home")}
          >
            <Home className="h-4 w-4" />
          </Link>
        </li>

        {segments.map((segment, index) => {
          const pathPrefix = locale === routing.defaultLocale ? "" : `/${locale}`;
          const href = pathPrefix + "/" + segments.slice(0, index + 1).join("/");
          const isLast = index === segments.length - 1;
          const label = getLabel(segment);

          return (
            <li key={href} className="flex items-center gap-1.5">
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              {isLast ? (
                <span
                  className="text-foreground font-medium truncate max-w-[200px]"
                  aria-current="page"
                >
                  {label}
                </span>
              ) : (
                <Link
                  href={href}
                  className="hover:text-foreground transition-colors hover:underline"
                >
                  {label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
