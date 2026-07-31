"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { api } from "@/lib/api";
import type { AuthorListingRow } from "@/lib/types";
import { AuthorAnalyticsPanel } from "@/components/author/AuthorAnalyticsPanel";
import { AuthorListingsTable } from "@/components/author/AuthorListingsTable";
import { AuthorOnboarding } from "@/components/author/AuthorOnboarding";
import { AuthorReviewsList } from "@/components/author/AuthorReviewsList";
import { LoadFailed } from "@/components/author/LoadFailed";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function AuthorModelsPage() {
  const t = useTranslations("author.page");
  const locale = useLocale();

  const [listings, setListings] = useState<AuthorListingRow[] | null>(null);
  // An outage must not read as "you haven't published anything yet" — that is a
  // statement about the author's work, and it would be a false one.
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const rows = await api.getAuthorListings();
        if (!cancelled) setListings(rows);
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
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
          {failed ? (
            <LoadFailed message={t("loadFailed")} />
          ) : listings === null ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <AuthorListingsTable listings={listings} onChanged={onChanged} />
          )}
        </TabsContent>

        <TabsContent value="analytics" className="mt-4">
          <AuthorAnalyticsPanel locale={locale} />
        </TabsContent>

        <TabsContent value="reviews" className="mt-4">
          {/* When the listings never arrived we don't know, so fall back to the
              wording that holds either way instead of guessing "nothing published". */}
          <AuthorReviewsList hasListings={listings === null ? true : listings.length > 0} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
