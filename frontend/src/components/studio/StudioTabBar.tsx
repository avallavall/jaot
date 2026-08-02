"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

const TABS = ["build", "data", "analyze", "solve"] as const;
type StudioTab = (typeof TABS)[number];

interface StudioTabBarProps {
  modelId: string;
}

/**
 * Top-level Build / Datos / Analyze / Solve tab bar (S4: D2 amended by owner —
 * "Datos" holds ALL input data). Each tab is a real link so tabs are
 * deep-linkable and back-button friendly.
 */
export function StudioTabBar({ modelId }: StudioTabBarProps) {
  const t = useTranslations("studio");
  const pathname = usePathname();

  const labels: Record<StudioTab, string> = {
    build: t("tabBuild"),
    data: t("tabData"),
    analyze: t("tabAnalyze"),
    solve: t("tabSolve"),
  };

  return (
    <div
      role="tablist"
      aria-label={t("tabsLabel")}
      className="flex items-center gap-1 border-b px-3"
    >
      {TABS.map((tab) => {
        const href = `/studio/${modelId}/${tab}`;
        const active = pathname === href;
        return (
          <Link
            key={tab}
            href={href}
            role="tab"
            data-testid={`studio-tab-${tab}`}
            aria-selected={active}
            className={cn(
              "px-4 py-2 text-sm -mb-px border-b-2 transition-colors",
              active
                ? "border-primary text-foreground font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {labels[tab]}
          </Link>
        );
      })}
    </div>
  );
}
