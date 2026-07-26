"use client";

import { useTranslations } from "next-intl";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { ModelCatalogItem } from "@/lib/types";

interface ModelTabsProps {
  model: ModelCatalogItem;
}

const TAB_SECTIONS = [
  { key: "overview", field: "section_overview" as const },
  { key: "features", field: "section_features" as const },
  { key: "howItWorks", field: "section_how_it_works" as const },
  { key: "exampleIo", field: "section_example_io" as const },
  { key: "changelog", field: "section_changelog" as const },
] as const;

// Tailwind only ships classes it can see in the source, so the column count is a
// lookup rather than an interpolated string.
const GRID_COLS: Record<number, string> = {
  1: "sm:grid-cols-1",
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-3",
  4: "sm:grid-cols-4",
  5: "sm:grid-cols-5",
};

/** Returns null when the model carries no section content — the caller falls back
 * to the plain description. Rendering the full strip regardless turned a model
 * with nothing filled in into five tabs of "the publisher hasn't added content",
 * which is noise the reader has to click through before reaching the description. */
export function ModelTabs({ model }: ModelTabsProps) {
  const t = useTranslations("marketplace.detail");
  const sections = TAB_SECTIONS.filter(({ field }) => model[field]);

  if (sections.length === 0) return null;

  return (
    <Tabs defaultValue={sections[0].key} className="w-full">
      <TabsList className={`flex w-full overflow-x-auto sm:grid ${GRID_COLS[sections.length]}`}>
        {sections.map(({ key }) => (
          <TabsTrigger key={key} value={key} className="whitespace-nowrap flex-shrink-0">
            {t(`tabs.${key}`)}
          </TabsTrigger>
        ))}
      </TabsList>
      {sections.map(({ key, field }) => (
        <TabsContent key={key} value={key} className="mt-4">
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <Markdown remarkPlugins={[remarkGfm]}>{model[field]}</Markdown>
          </div>
        </TabsContent>
      ))}
    </Tabs>
  );
}
