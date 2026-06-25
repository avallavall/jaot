"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Heart, Package, Shield, Star, Zap } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ModelCatalogItem } from "@/lib/types";
import { useTemplateTranslation } from "@/hooks/useTemplateTranslation";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";

interface MarketplaceModelCardProps {
  model: ModelCatalogItem;
  /** When true, show activate/favorite/open controls */
  isAuthenticated?: boolean;
  /** Whether the model is already activated for the user's org */
  isActivated?: boolean;
  /** Whether the model is in the user's favorites */
  isFavorite?: boolean;
  /** Toggle favorite handler */
  onToggleFavorite?: (e: React.MouseEvent) => void;
  /** Activate model handler */
  onActivate?: () => void;
  /** Navigate to user's activated copy */
  onGoToModel?: () => void;
}

export function MarketplaceModelCard({
  model,
  isAuthenticated = false,
  isActivated = false,
  isFavorite = false,
  onToggleFavorite,
  onActivate,
  onGoToModel,
}: MarketplaceModelCardProps) {
  const t = useTranslations("marketplace.card");
  const { categoryLabel } = useCommonLabels();
  const tmpl = useTemplateTranslation(model.id);

  return (
    <Link href={`/marketplace/${model.id}`} className="block h-full">
      <Card className="h-full flex flex-col gap-0 py-0 overflow-hidden hover:shadow-lg transition-shadow cursor-pointer">
        <div className="relative h-32 w-full overflow-hidden">
          {model.logo_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={model.logo_url}
              alt={model.display_name}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="h-full w-full bg-gradient-to-br from-muted to-muted/50 flex items-center justify-center">
              <Package className="w-12 h-12 text-muted-foreground/40" />
            </div>
          )}

          {/* Favorite heart button (auth only) */}
          {isAuthenticated && onToggleFavorite && (
            <button
              onClick={onToggleFavorite}
              className={cn(
                "absolute top-2 right-2 p-1.5 rounded-full transition-colors z-20",
                "bg-background/80 backdrop-blur-sm hover:bg-background",
                isFavorite
                  ? "text-red-500 hover:text-red-600"
                  : "text-muted-foreground hover:text-red-500"
              )}
              title={isFavorite ? t("removeFromFavorites") : t("addToFavorites")}
              aria-label={isFavorite ? t("removeFromFavorites") : t("addToFavorites")}
            >
              <Heart className={cn("w-4 h-4", isFavorite && "fill-current")} />
            </button>
          )}
        </div>

        {/* Card header: name + description */}
        <CardHeader className="pb-2 pt-4">
          <h3 className="text-base font-semibold leading-tight line-clamp-1">
            {tmpl.displayName(model.display_name)}
          </h3>
          <p className="text-sm text-muted-foreground line-clamp-2 mt-1">
            {tmpl.shortDescription(
              model.short_description || model.description || ""
            )}
          </p>
        </CardHeader>

        {/* Card content: metadata */}
        <CardContent className="mt-auto pb-4 pt-2">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <Badge variant="outline" className="text-xs">
                {categoryLabel(model.category)}
              </Badge>

              {model.avg_rating != null ? (
                <span className="inline-flex items-center gap-1 text-sm">
                  <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                  {model.avg_rating.toFixed(1)}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">
                  {t("newModel")}
                </span>
              )}
            </div>

            {model.total_activations > 0 && (
              <div className="flex items-center justify-end gap-2 text-sm">
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Zap className="w-3 h-3" />
                  {model.total_activations.toLocaleString()}
                </span>
              </div>
            )}

            {model.author_name && (
              <div className="text-xs text-muted-foreground truncate">
                <span
                  role="link"
                  tabIndex={0}
                  className="hover:underline cursor-pointer"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    window.location.href = `/marketplace/sellers/${model.author_organization_id}`;
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      e.stopPropagation();
                      window.location.href = `/marketplace/sellers/${model.author_organization_id}`;
                    }
                  }}
                >
                  {t("by", { author: model.author_name })}
                </span>
                {model.author_verified && (
                  <span className="inline-flex items-center gap-0.5 text-blue-600 ml-1" title={t("verified")}>
                    <Shield className="w-3 h-3 fill-blue-600" />
                  </span>
                )}
              </div>
            )}

            {/* Action buttons (auth only) */}
            {isAuthenticated && (
              <div className="flex gap-2 pt-1 border-t mt-1">
                {isActivated ? (
                  <Button
                    size="sm"
                    variant="default"
                    className="flex-1"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onGoToModel?.();
                    }}
                  >
                    {t("open")}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="default"
                    className="flex-1"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onActivate?.();
                    }}
                  >
                    {t("activate")}
                  </Button>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
