"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import Autoplay from "embla-carousel-autoplay";
import { Package, Star, Zap } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ModelCatalogItem } from "@/lib/types";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
  type CarouselApi,
} from "@/components/ui/carousel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// Category-based gradient backgrounds
const CATEGORY_GRADIENTS: Record<string, string> = {
  scheduling: "from-blue-500/10 to-blue-600/5",
  logistics: "from-green-500/10 to-green-600/5",
  finance: "from-emerald-500/10 to-emerald-600/5",
  routing: "from-orange-500/10 to-orange-600/5",
  assignment: "from-purple-500/10 to-purple-600/5",
  linear: "from-sky-500/10 to-sky-600/5",
  integer: "from-indigo-500/10 to-indigo-600/5",
  mixed_integer: "from-violet-500/10 to-violet-600/5",
  nonlinear: "from-rose-500/10 to-rose-600/5",
  quadratic: "from-pink-500/10 to-pink-600/5",
  network: "from-teal-500/10 to-teal-600/5",
};

const DEFAULT_GRADIENT = "from-primary/10 to-primary/5";

interface FeaturedCarouselProps {
  models: ModelCatalogItem[];
  promotedModelIds?: string[];
}

export function FeaturedCarousel({ models, promotedModelIds = [] }: FeaturedCarouselProps) {
  const t = useTranslations("marketplace.hero");
  const { categoryLabel } = useCommonLabels();
  const [api, setApi] = useState<CarouselApi>();
  const [current, setCurrent] = useState(0);

  const onSelect = useCallback(() => {
    if (!api) return;
    setCurrent(api.selectedScrollSnap());
  }, [api]);

  useEffect(() => {
    if (!api) return;
    onSelect();
    api.on("select", onSelect);
    return () => {
      api.off("select", onSelect);
    };
  }, [api, onSelect]);

  if (models.length === 0) return null;

  return (
    <div className="relative">
      <Carousel
        setApi={setApi}
        plugins={[
          Autoplay({
            delay: 5000,
            stopOnInteraction: true,
            stopOnMouseEnter: true,
          }),
        ]}
        opts={{ loop: true }}
        className="w-full"
      >
        <CarouselContent>
          {models.map((model) => {
            const gradient =
              CATEGORY_GRADIENTS[model.category] ?? DEFAULT_GRADIENT;
            const isPromoted = promotedModelIds.includes(model.id);

            return (
              <CarouselItem key={model.id}>
                <div
                  className={cn(
                    "relative min-h-[280px] rounded-xl bg-gradient-to-r p-8 flex items-center",
                    gradient
                  )}
                >
                  {isPromoted && (
                    <Badge
                      variant="secondary"
                      className="absolute top-4 right-4 text-xs"
                    >
                      {t("promoted")}
                    </Badge>
                  )}

                  <div className="flex items-center justify-between w-full gap-8">
                    {/* Left side: model info */}
                    <div className="flex items-center gap-6 flex-1 min-w-0">
                      <div className="shrink-0 w-24 h-24 rounded-xl bg-background/80 flex items-center justify-center overflow-hidden border">
                        {model.logo_url ? (
                          /* eslint-disable-next-line @next/next/no-img-element */
                          <img
                            src={model.logo_url}
                            alt={model.display_name}
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <Package className="w-10 h-10 text-muted-foreground" />
                        )}
                      </div>

                      <div className="flex flex-col gap-3 min-w-0">
                        <div>
                          <h2 className="text-2xl font-bold tracking-tight line-clamp-1">
                            {model.display_name}
                          </h2>
                          <p className="text-muted-foreground mt-1 line-clamp-2 max-w-lg">
                            {model.short_description || model.description}
                          </p>
                        </div>

                        <div className="flex items-center gap-3 flex-wrap">
                          <Badge variant="secondary">
                            {categoryLabel(model.category)}
                          </Badge>

                          {model.avg_rating != null && (
                            <span className="inline-flex items-center gap-1 text-sm">
                              <Star className="w-4 h-4 fill-amber-400 text-amber-400" />
                              {model.avg_rating.toFixed(1)}
                            </span>
                          )}

                          {model.total_activations > 0 && (
                            <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                              <Zap className="w-4 h-4" />
                              {t("activations", {
                                count: model.total_activations,
                              })}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Right side: CTA */}
                    <div className="shrink-0">
                      <Button asChild size="lg">
                        <Link href={`/marketplace/${model.id}`}>
                          {t("viewModel")}
                        </Link>
                      </Button>
                    </div>
                  </div>
                </div>
              </CarouselItem>
            );
          })}
        </CarouselContent>

        <CarouselPrevious className="-left-4 lg:-left-12" />
        <CarouselNext className="-right-4 lg:-right-12" />
      </Carousel>

      {models.length > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          {models.map((_, i) => (
            <button
              key={i}
              type="button"
              className={cn(
                "w-2.5 h-2.5 rounded-full transition-colors",
                i === current
                  ? "bg-primary"
                  : "bg-muted-foreground/30 hover:bg-muted-foreground/50"
              )}
              onClick={() => api?.scrollTo(i)}
              aria-label={t("goToSlide", { number: i + 1 })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
