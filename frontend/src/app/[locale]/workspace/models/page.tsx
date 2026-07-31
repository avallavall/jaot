"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { api } from "@/lib/api";
import type { AuthorListingRow } from "@/lib/types";
import { AuthorAnalyticsPanel } from "@/components/author/AuthorAnalyticsPanel";
import { AuthorListingsTable } from "@/components/author/AuthorListingsTable";
import { AuthorOnboarding } from "@/components/author/AuthorOnboarding";
import { AuthorReviewsList } from "@/components/author/AuthorReviewsList";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function AuthorModelsPage() {
  const t = useTranslations("author.page");
  const locale = useLocale();

  const [listings, setListings] = useState<AuthorListingRow[] | null>(null);

  useEffect(() => {
    api
      .getAuthorListings()
      .then(setListings)
      .catch(() => setListings([]));
  }, []);

  const onChanged = (updated: AuthorListingRow) => {
    setListings((rows) =>
      rows
        ? rows.map((r) =>
            r.model_project_id === updated.model_project_id ? updated : r,
          )
        : rows,
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <AuthorOnboarding />

      <Tabs defaultValue="listings">
        <TabsList>
          <TabsTrigger value="listings">{t("tabListings")}</TabsTrigger>
          <TabsTrigger value="analytics">{t("tabAnalytics")}</TabsTrigger>
          <TabsTrigger value="reviews">{t("tabReviews")}</TabsTrigger>
        </TabsList>

        <TabsContent value="listings" className="mt-4">
          {listings === null ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <AuthorListingsTable listings={listings} onChanged={onChanged} />
          )}
        </TabsContent>

        <TabsContent value="analytics" className="mt-4">
          <AuthorAnalyticsPanel locale={locale} />
        </TabsContent>

        <TabsContent value="reviews" className="mt-4">
          <AuthorReviewsList hasListings={(listings?.length ?? 0) > 0} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
