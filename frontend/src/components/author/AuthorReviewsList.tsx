"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { MessageSquare, Star } from "lucide-react";

import { api } from "@/lib/api";
import type { AuthorReviews } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const PAGE_SIZE = 10;

function Stars({ rating }: { rating: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${rating}/5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={
            i <= rating ? "h-3 w-3 fill-current text-amber-500" : "h-3 w-3 text-muted-foreground/40"
          }
        />
      ))}
    </span>
  );
}

export function AuthorReviewsList({ hasListings }: { hasListings: boolean }) {
  const t = useTranslations("author.reviews");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AuthorReviews | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // `cancelled` also settles the page race: clicking through pages fast could
    // otherwise land an older response on top of a newer one.
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const result = await api.getAuthorReviews({ page, page_size: PAGE_SIZE });
        if (!cancelled) setData(result);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [page]);

  if (loading) return <Skeleton className="h-40 w-full" />;

  if (!data || data.total === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <MessageSquare className="h-8 w-8 text-muted-foreground" />
          <p className="font-medium">{t("emptyTitle")}</p>
          <p className="max-w-md text-sm text-muted-foreground">
            {hasListings ? t("emptyBodyPublished") : t("emptyBodyNothingPublished")}
          </p>
        </CardContent>
      </Card>
    );
  }

  const pages = Math.ceil(data.total / PAGE_SIZE);

  return (
    <div className="space-y-4">
      {data.reviews.map((review) => (
        <Card key={review.id}>
          <CardContent className="space-y-2 pt-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Stars rating={review.rating} />
                {review.title && <span className="font-medium">{review.title}</span>}
              </div>
              <span className="text-xs text-muted-foreground">
                {new Date(review.created_at).toLocaleDateString()}
              </span>
            </div>
            {review.comment && <p className="text-sm">{review.comment}</p>}
            <p className="text-xs text-muted-foreground">
              {t("onModel", { model: review.model_display_name })}
              {review.reviewer_name ? ` · ${review.reviewer_name}` : ""}
            </p>
          </CardContent>
        </Card>
      ))}

      {pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            {t("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pageOf", { page, pages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            {t("next")}
          </Button>
        </div>
      )}
    </div>
  );
}
