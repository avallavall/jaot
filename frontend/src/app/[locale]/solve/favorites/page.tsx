"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { api } from "@/lib/api";
interface FavoriteModel {
  id: string;
  display_name: string;
  author_name?: string;
  description?: string;
  is_official?: boolean;
  is_featured?: boolean;
  avg_rating?: number;
}

interface RecentModel {
  id: string;
  display_name: string;
  author_name?: string;
  category?: string;
  last_accessed: string;
  access_count: number;
}
import { 
  Heart, 
  Star, 
  Play, 
  Clock,
  Sparkles,
  Award,
} from "lucide-react";

export default function FavoritesPage() {
  const t = useTranslations("solve.favorites");
  const { categoryLabel } = useCommonLabels();
  const [favorites, setFavorites] = useState<FavoriteModel[]>([]);
  const [recents, setRecents] = useState<RecentModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"favorites" | "recents">("favorites");

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [favData, recentData] = await Promise.all([
        api.request("/api/v2/models/favorites") as Promise<{ items: FavoriteModel[] }>,
        api.request("/api/v2/models/recents?limit=20") as Promise<{ items: RecentModel[] }>,
      ]);
      setFavorites(favData.items || []);
      setRecents(recentData.items || []);
    } catch (err) {
      console.warn('Failed to load favorites:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveFavorite = async (modelId: string) => {
    // Optimistic: remove from list immediately
    const previousFavorites = favorites;
    setFavorites((prev) => prev.filter((f) => f.id !== modelId));
    try {
      await api.request(`/api/v2/models/favorites/${modelId}`, {
        method: "DELETE",
      });
    } catch {
      // Revert on failure
      setFavorites(previousFavorites);
      toast.error(t("removeFailed"));
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);
    
    if (hours < 1) return t("justNow");
    if (hours < 24) return t("hoursAgo", { count: hours });
    if (days < 7) return t("daysAgo", { count: days });
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <div className="flex gap-2 border-b">
        <button
          onClick={() => setActiveTab("favorites")}
          className={`px-4 py-2 font-medium transition-colors ${
            activeTab === "favorites"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Heart className="inline-block w-4 h-4 mr-2" />
          {t("favoritesTab", { count: favorites.length })}
        </button>
        <button
          onClick={() => setActiveTab("recents")}
          className={`px-4 py-2 font-medium transition-colors ${
            activeTab === "recents"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Clock className="inline-block w-4 h-4 mr-2" />
          {t("recentTab", { count: recents.length })}
        </button>
      </div>

      {activeTab === "favorites" && (
        <div>
          {favorites.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Heart className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                <h3 className="text-lg font-medium mb-2">{t("noFavorites")}</h3>
                <p className="text-muted-foreground mb-4">
                  {t("noFavoritesDescription")}
                </p>
                <Link href="/marketplace">
                  <Button>{t("browseCatalog")}</Button>
                </Link>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {favorites.map((model) => (
                <Card key={model.id} className="hover:shadow-md transition-shadow">
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <CardTitle className="text-lg line-clamp-1">
                          {model.display_name}
                        </CardTitle>
                        <p className="text-sm text-muted-foreground">
                          {t("by", { author: model.author_name ?? "" })}
                        </p>
                      </div>
                      <button
                        onClick={() => handleRemoveFavorite(model.id)}
                        className="text-red-500 hover:text-red-600 p-1"
                        title={t("removeFromFavorites")}
                      >
                        <Heart className="w-5 h-5 fill-current" />
                      </button>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-2 mb-3">
                      {model.is_official && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-700">
                          <Award className="w-3 h-3" /> {t("official")}
                        </span>
                      )}
                      {model.is_featured && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700">
                          <Sparkles className="w-3 h-3" /> {t("featuredBadge")}
                        </span>
                      )}
                      {model.avg_rating && (
                        <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                          <Star className="w-4 h-4 fill-amber-400 text-amber-400" />
                          {model.avg_rating.toFixed(1)}
                        </span>
                      )}
                    </div>
                    {model.description && (
                      <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
                        {model.description}
                      </p>
                    )}
                    <div className="flex gap-2">
                      <Link href={`/solve/${model.id}`} className="flex-1">
                        <Button size="sm" className="w-full">
                          <Play className="w-4 h-4 mr-1" /> {t("run")}
                        </Button>
                      </Link>
                      <Link href={`/marketplace/${model.id}`}>
                        <Button size="sm" variant="outline">
                          {t("details")}
                        </Button>
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "recents" && (
        <div>
          {recents.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Clock className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                <h3 className="text-lg font-medium mb-2">{t("noRecent")}</h3>
                <p className="text-muted-foreground mb-4">
                  {t("noRecentDescription")}
                </p>
                <Link href="/marketplace">
                  <Button>{t("browseCatalog")}</Button>
                </Link>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {recents.map((model) => (
                <Card key={model.id} className="hover:shadow-sm transition-shadow">
                  <CardContent className="py-3">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <Link 
                          href={`/solve/${model.id}`}
                          className="font-medium hover:text-primary"
                        >
                          {model.display_name}
                        </Link>
                        <p className="text-sm text-muted-foreground">
                          {model.author_name} • {categoryLabel(model.category || "")}
                        </p>
                      </div>
                      <div className="flex items-center gap-4">
                        <div className="text-right text-sm text-muted-foreground">
                          <div>{formatDate(model.last_accessed)}</div>
                          <div>{t("accessCount", { count: model.access_count })}</div>
                        </div>
                        <Link href={`/solve/${model.id}`}>
                          <Button size="sm">
                            <Play className="w-4 h-4" />
                          </Button>
                        </Link>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
