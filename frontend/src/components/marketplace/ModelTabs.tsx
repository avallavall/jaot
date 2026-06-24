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

export function ModelTabs({ model }: ModelTabsProps) {
  const t = useTranslations("marketplace.detail");

  return (
    <Tabs defaultValue="overview" className="w-full">
      <TabsList className="flex w-full overflow-x-auto sm:grid sm:grid-cols-5">
        {TAB_SECTIONS.map(({ key }) => (
          <TabsTrigger key={key} value={key} className="whitespace-nowrap flex-shrink-0">
            {t(`tabs.${key}`)}
          </TabsTrigger>
        ))}
      </TabsList>
      {TAB_SECTIONS.map(({ key, field }) => (
        <TabsContent key={key} value={key} className="mt-4">
          {model[field] ? (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <Markdown remarkPlugins={[remarkGfm]}>{model[field]}</Markdown>
            </div>
          ) : (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-lg mb-2">{t(`tabs.${key}Empty`)}</p>
              <p className="text-sm">{t("tabs.emptyHint")}</p>
            </div>
          )}
        </TabsContent>
      ))}
    </Tabs>
  );
}
