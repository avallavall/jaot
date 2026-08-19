"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { OrgProfile, ModelCatalogItem } from "@/lib/types";
import type { LucideIcon } from "lucide-react";
import {
  Building2,
  Shield,
  Calendar,
  Package,
  Star,
  Zap,
  ChevronLeft,
  Globe,
  Linkedin,
  Twitter,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketplaceModelCard } from "@/components/marketplace/MarketplaceModelCard";
import { apiDate } from "@/lib/dates";
import { useDateFormat } from "@/hooks/useDateFormat";

/** How many of an author's models one page holds. Matches the endpoint's own
 * default, so the page number can be derived from how many are already shown. */
const AUTHOR_MODELS_PAGE_SIZE = 50;

function StatCard({
  icon: Icon,
  label,
  value,
  note,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  /** What the number is built on, when the number alone would overstate it. */
  note?: string;
}) {
  return (
    <Card className="text-center">
      <CardContent className="pt-6">
        <Icon className="w-6 h-6 mx-auto mb-2 text-primary" />
        <div className="text-2xl font-bold">{value}</div>
        <div className="text-sm text-muted-foreground">{label}</div>
        {note ? <div className="mt-1 text-xs text-muted-foreground">{note}</div> : null}
      </CardContent>
    </Card>
  );
}

function ProfileSkeleton() {
  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <Skeleton className="h-5 w-40" />

      <Card>
        <CardContent className="p-6">
          <div className="flex items-start gap-6">
            <Skeleton className="w-20 h-20 rounded-xl" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-8 w-64" />
              <Skeleton className="h-4 w-48" />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i} className="text-center">
            <CardContent className="pt-6 space-y-2">
              <Skeleton className="w-6 h-6 mx-auto rounded" />
              <Skeleton className="h-7 w-16 mx-auto" />
              <Skeleton className="h-4 w-24 mx-auto" />
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="space-y-4">
        <Skeleton className="h-6 w-48" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-64 rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function AuthorProfileClient({ orgId }: { orgId: string }) {
  const t = useTranslations("marketplace.authorProfile");
  const { day } = useDateFormat();

  const [profile, setProfile] = useState<OrgProfile | null>(null);
  const [models, setModels] = useState<ModelCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // `t` is used only for the fallback message in the error branch, so it is
  // held in a ref rather than listed as a dependency. As a dependency it
  // re-ran the whole load on every render that handed back a new translator
  // identity — two requests for one author page, and the second one racing the
  // first to set the list.
  const tRef = useRef(t);
  useEffect(() => {
    tRef.current = t;
  });

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [profileData, modelsData] = await Promise.all([
          api.getOrgProfile(orgId),
          api.getOrgModels(orgId, 1, AUTHOR_MODELS_PAGE_SIZE),
        ]);
        setProfile(profileData);
        setModels(modelsData);
      } catch (err) {
        setError(getErrorMessage(err, tRef.current("failedToLoad")));
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [orgId]);

  // The list took a fixed fifty and stopped there with nothing to say more
  // existed, while the header above it reported the real total: 52 of the
  // biggest author's 102 models could not be reached from their own page.
  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = await api.getOrgModels(
        orgId,
        Math.floor(models.length / AUTHOR_MODELS_PAGE_SIZE) + 1,
        AUTHOR_MODELS_PAGE_SIZE
      );
      setModels((current) => [...current, ...next]);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoadingMore(false);
    }
  }

  if (loading) {
    return <ProfileSkeleton />;
  }

  if (error || !profile) {
    return (
      <div className="max-w-6xl mx-auto py-16 text-center">
        <p className="text-destructive mb-4">{error || t("authorNotFound")}</p>
        <Link
          href="/marketplace"
          className="text-sm text-primary hover:underline"
        >
          {t("backToMarketplace")}
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <Link
        href="/marketplace"
        className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
      >
        <ChevronLeft className="w-4 h-4" />
        {t("backToMarketplace")}
      </Link>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-start gap-6">
            {profile.logo_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={profile.logo_url}
                alt=""
                className="w-20 h-20 rounded-xl object-cover"
              />
            ) : (
              <div className="w-20 h-20 rounded-xl bg-muted flex items-center justify-center">
                <Building2 className="w-10 h-10 text-muted-foreground" />
              </div>
            )}

            <div className="flex-1">
              <div className="flex items-center gap-3">
                <h1 className="text-3xl font-serif">{profile.name}</h1>
                {profile.is_verified && (
                  <Badge variant="default" className="gap-1">
                    <Shield className="w-3 h-3" />
                    {t("verified")}
                  </Badge>
                )}
              </div>
              <div className="text-sm text-muted-foreground mt-1 flex items-center gap-1">
                <Calendar className="w-4 h-4" />
                {t("memberSince")}{" "}
                {day(profile.created_at)}
              </div>
              {(profile.website_url ||
                profile.linkedin_url ||
                profile.twitter_url) && (
                <div className="flex gap-3 mt-2">
                  {profile.website_url && (
                    <a
                      href={profile.website_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <Globe className="w-5 h-5" />
                    </a>
                  )}
                  {profile.linkedin_url && (
                    <a
                      href={profile.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <Linkedin className="w-5 h-5" />
                    </a>
                  )}
                  {profile.twitter_url && (
                    <a
                      href={profile.twitter_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <Twitter className="w-5 h-5" />
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={Package}
          label={t("modelsPublished")}
          value={profile.total_models_published}
        />
        <StatCard
          icon={Zap}
          label={t("totalActivations")}
          value={profile.total_activations}
        />
        {/* A 5.0 built on one review out of a hundred models reads as "a hundred
            models rated 5.0". The card grid below is honest about it — an
            unrated model says "New" — so the headline that frames the whole
            author has to be too. */}
        <StatCard
          icon={Star}
          label={t("avgRating")}
          value={
            profile.avg_rating ? profile.avg_rating.toFixed(1) : t("noRating")
          }
          note={
            profile.avg_rating
              ? t("avgRatingFrom", { count: profile.total_reviews })
              : undefined
          }
        />
        <StatCard
          icon={Calendar}
          label={t("memberSince")}
          value={apiDate(profile.created_at).getFullYear()}
        />
      </div>

      {profile.bio && (
        <section>
          <h2 className="text-xl font-semibold mb-3">{t("bio")}</h2>
          <p className="text-muted-foreground whitespace-pre-line">
            {profile.bio}
          </p>
        </section>
      )}

      <section>
        <h2 className="text-xl font-semibold mb-4">{t("publishedModels")}</h2>
        {models.length === 0 ? (
          <p className="text-muted-foreground py-8 text-center">
            {t("noModels")}
          </p>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {models.map((model) => (
                <MarketplaceModelCard key={model.id} model={model} />
              ))}
            </div>
            {models.length < profile.total_models_published && (
              <div className="mt-6 text-center">
                <Button
                  variant="outline"
                  onClick={loadMore}
                  disabled={loadingMore}
                  data-testid="author-load-more"
                >
                  {loadingMore
                    ? t("loadingMore")
                    : t("loadMore", {
                        remaining: profile.total_models_published - models.length,
                      })}
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
