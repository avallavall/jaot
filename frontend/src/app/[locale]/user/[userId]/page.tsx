"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  User,
  Building2,
  Star,
  CheckCircle,
  ArrowLeft,
  Calendar,
  Award,
} from "lucide-react";
import { api } from "@/lib/api";
import type { UserProfile, Review } from "@/lib/types";

type UserPublicProfile = UserProfile & { created_at?: string };
interface UserReview extends Review {
  model_name?: string;
}

export default function UserProfilePage() {
  const params = useParams();
  const router = useRouter();
  const userId = params.userId as string;
  const t = useTranslations("workspace.userPublicProfile");

  const [profile, setProfile] = useState<UserPublicProfile | null>(null);
  const [reviews, setReviews] = useState<UserReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const loadProfile = async () => {
    setLoading(true);
    setError(null);
    try {
      const profileData = await api.getUserProfile(userId);
      setProfile(profileData);

      try {
        const reviewsData = await api.getUserReviews(userId);
        setReviews(Array.isArray(reviewsData) ? reviewsData : []);
      } catch (err) {
        console.warn('Failed to load user reviews:', err);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
    });
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
          {error || t("userNotFound")}
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
          <div className="w-24 h-24 bg-muted rounded-full flex items-center justify-center flex-shrink-0">
            <User className="w-12 h-12 text-muted-foreground" />
          </div>

          <div className="flex-1">
            <h1 className="text-2xl font-bold mb-2">{profile.name}</h1>

            <Link
              href={`/org/${profile.organization_id}`}
              className="flex items-center gap-2 text-muted-foreground hover:text-foreground mb-4"
            >
              <Building2 className="w-4 h-4" />
              <span>{profile.organization_name}</span>
              {profile.organization_verified && (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
                  <CheckCircle className="w-3 h-3" />
                  {t("verified")}
                </span>
              )}
            </Link>

            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Calendar className="w-4 h-4" />
              {profile.created_at && <>{t("memberSince", { date: formatDate(profile.created_at) })}</>}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 mt-8 pt-6 border-t">
          <div className="text-center">
            <div className="text-2xl font-bold text-primary">
              {profile.total_reviews}
            </div>
            <div className="text-sm text-muted-foreground">{t("reviewsWritten")}</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-primary flex items-center justify-center gap-1">
              {profile.avg_rating_given ? (
                <>
                  <Star className="w-5 h-5 fill-current" />
                  {profile.avg_rating_given.toFixed(1)}
                </>
              ) : (
                "\u2014"
              )}
            </div>
            <div className="text-sm text-muted-foreground">{t("avgRatingGiven")}</div>
          </div>
        </div>
      </div>

      {/* User's Reviews */}
      <div>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Award className="w-5 h-5" />
          {t("reviewsBy", { name: profile.name })}
        </h2>

        {reviews.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground bg-card border rounded-lg">
            {t("noReviews")}
          </div>
        ) : (
          <div className="space-y-4">
            {reviews.map((review) => (
              <div
                key={review.id}
                className="bg-card border rounded-lg p-4"
              >
                <div className="flex items-start justify-between mb-2">
                  <Link
                    href={`/marketplace/${review.catalog_id}`}
                    className="font-semibold hover:text-primary"
                  >
                    {review.model_name}
                  </Link>
                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <Star
                        key={star}
                        className={`w-4 h-4 ${
                          star <= review.rating
                            ? "fill-current text-primary"
                            : "text-muted-foreground"
                        }`}
                      />
                    ))}
                  </div>
                </div>

                {review.title && (
                  <h4 className="font-medium mb-1">{review.title}</h4>
                )}

                {review.comment && (
                  <p className="text-sm text-muted-foreground mb-2">
                    {review.comment}
                  </p>
                )}

                <div className="text-xs text-muted-foreground">
                  {formatDate(review.created_at)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
