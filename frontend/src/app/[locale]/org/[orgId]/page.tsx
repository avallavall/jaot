"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Building2,
  Globe,
  Linkedin,
  Twitter,
  Star,
  Users,
  CheckCircle,
  ArrowLeft,
  ExternalLink,
} from "lucide-react";
import type { OrgProfile, ModelCatalogItem } from "@/lib/types";

type OrganizationPublicProfile = OrgProfile;
type PublishedModel = ModelCatalogItem;

export default function OrganizationProfilePage() {
  const params = useParams();
  const router = useRouter();
  const orgId = params.orgId as string;
  const t = useTranslations("workspace.orgPublicProfile");

  const [profile, setProfile] = useState<OrganizationPublicProfile | null>(null);
  const [models, setModels] = useState<PublishedModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  const loadProfile = async () => {
    setLoading(true);
    setError(null);
    try {
      const profileData = await api.getOrgProfile(orgId);
      setProfile(profileData);

      try {
        const modelsData = await api.getOrgModels(orgId);
        setModels(Array.isArray(modelsData) ? modelsData : []);
      } catch (err) {
        console.warn('Failed to load organization models:', err);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg mb-4">
          {error || t("orgNotFound")}
        </div>
        <Button onClick={() => router.push("/marketplace")}>
          {t("backToCatalog")}
        </Button>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <Link
        href="/marketplace"
        className="flex items-center gap-2 text-muted-foreground hover:text-foreground mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        {t("backToCatalog")}
      </Link>

      <div className="bg-card border rounded-lg p-8 mb-8">
        <div className="flex items-start gap-6">
          <div className="w-24 h-24 bg-muted rounded-lg flex items-center justify-center flex-shrink-0">
            {profile.logo_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={profile.logo_url}
                alt={profile.name}
                className="w-full h-full object-cover rounded-lg"
              />
            ) : (
              <Building2 className="w-12 h-12 text-muted-foreground" />
            )}
          </div>

          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-2xl font-bold">{profile.name}</h1>
              {profile.is_verified && (
                <span className="flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
                  <CheckCircle className="w-3 h-3" />
                  {t("verified")}
                </span>
              )}
            </div>

            {profile.bio && (
              <p className="text-muted-foreground mb-4">{profile.bio}</p>
            )}

            <div className="flex items-center gap-4">
              {profile.website_url && (
                <a
                  href={profile.website_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
                >
                  <Globe className="w-4 h-4" />
                  {t("website")}
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
              {profile.linkedin_url && (
                <a
                  href={profile.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
                >
                  <Linkedin className="w-4 h-4" />
                  LinkedIn
                </a>
              )}
              {profile.twitter_url && (
                <a
                  href={profile.twitter_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
                >
                  <Twitter className="w-4 h-4" />
                  Twitter
                </a>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-5 gap-4 mt-8 pt-6 border-t">
          <div className="text-center">
            <div className="text-2xl font-bold text-primary">
              {profile.total_models_published ?? 0}
            </div>
            <div className="text-sm text-muted-foreground">{t("models")}</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-primary">
              {(profile.total_activations ?? 0).toLocaleString()}
            </div>
            <div className="text-sm text-muted-foreground">{t("activations")}</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-primary">
              {(profile.total_executions ?? 0).toLocaleString()}
            </div>
            <div className="text-sm text-muted-foreground">{t("executions")}</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-primary">
              {profile.total_reviews ?? 0}
            </div>
            <div className="text-sm text-muted-foreground">{t("reviews")}</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-primary flex items-center justify-center gap-1">
              {profile.avg_rating ? (
                <>
                  <Star className="w-5 h-5 fill-current" />
                  {profile.avg_rating.toFixed(1)}
                </>
              ) : (
                "\u2014"
              )}
            </div>
            <div className="text-sm text-muted-foreground">{t("avgRating")}</div>
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">{t("publishedModels")}</h2>

        {models.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground bg-card border rounded-lg">
            {t("noModels")}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {models.map((model) => (
              <Link
                key={model.id}
                href={`/marketplace/${model.id}`}
                className="bg-card border rounded-lg p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-semibold">{model.display_name}</h3>
                  {model.avg_rating && (
                    <span className="flex items-center gap-1 text-sm">
                      <Star className="w-4 h-4 fill-current text-primary" />
                      {model.avg_rating.toFixed(1)}
                    </span>
                  )}
                </div>

                {model.description && (
                  <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
                    {model.description}
                  </p>
                )}

                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Users className="w-3 h-3" />
                    {t("activationCount", { count: model.total_activations ?? 0 })}
                  </span>
                  <span>
                    {(model.price_eur ?? 0) === 0 ? (
                      <span className="text-green-600 font-medium">{t("free")}</span>
                    ) : (
                      `${(model.price_eur ?? 0).toFixed(2)} \u20ac`
                    )}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
