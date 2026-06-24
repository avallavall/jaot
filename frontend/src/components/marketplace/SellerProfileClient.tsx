"use client";

import { useState, useEffect } from "react";
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
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketplaceModelCard } from "@/components/marketplace/MarketplaceModelCard";

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
}) {
  return (
    <Card className="text-center">
      <CardContent className="pt-6">
        <Icon className="w-6 h-6 mx-auto mb-2 text-primary" />
        <div className="text-2xl font-bold">{value}</div>
        <div className="text-sm text-muted-foreground">{label}</div>
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

export function SellerProfileClient({ orgId }: { orgId: string }) {
  const t = useTranslations("marketplace.sellerProfile");

  const [profile, setProfile] = useState<OrgProfile | null>(null);
  const [models, setModels] = useState<ModelCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [profileData, modelsData] = await Promise.all([
          api.getOrgProfile(orgId),
          api.getOrgModels(orgId),
        ]);
        setProfile(profileData);
        setModels(modelsData);
      } catch (err) {
        setError(getErrorMessage(err, t("failedToLoad")));
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [orgId, t]);

  if (loading) {
    return <ProfileSkeleton />;
  }

  if (error || !profile) {
    return (
      <div className="max-w-6xl mx-auto py-16 text-center">
        <p className="text-destructive mb-4">{error || t("sellerNotFound")}</p>
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
                {new Date(profile.created_at).toLocaleDateString()}
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
        <StatCard
          icon={Star}
          label={t("avgRating")}
          value={
            profile.avg_rating ? profile.avg_rating.toFixed(1) : t("noRating")
          }
        />
        <StatCard
          icon={Calendar}
          label={t("memberSince")}
          value={new Date(profile.created_at).getFullYear()}
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
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {models.map((model) => (
              <MarketplaceModelCard key={model.id} model={model} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
