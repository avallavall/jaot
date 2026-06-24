"use client";

import { useTranslations } from "next-intl";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

interface RatingFilterProps {
  value: number | null;
  onChange: (value: number | null) => void;
}

const RATING_OPTIONS = [4, 3, 2, 1] as const;

export function RatingFilter({ value, onChange }: RatingFilterProps) {
  const t = useTranslations("marketplace.filters");

  return (
    <div className="space-y-1">
      {RATING_OPTIONS.map((rating) => {
        const isSelected = value === rating;
        return (
          <button
            key={rating}
            type="button"
            className={cn(
              "flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm transition-colors hover:bg-accent",
              isSelected && "bg-accent"
            )}
            onClick={() => onChange(isSelected ? null : rating)}
          >
            <span className="flex items-center gap-0.5">
              {Array.from({ length: 5 }, (_, i) => (
                <Star
                  key={i}
                  className={cn(
                    "w-3.5 h-3.5",
                    i < rating
                      ? "fill-amber-400 text-amber-400"
                      : "text-muted-foreground"
                  )}
                />
              ))}
            </span>
            <span className={cn(
              "text-muted-foreground",
              isSelected && "text-accent-foreground"
            )}>
              {t("ratingUp", { stars: rating })}
            </span>
          </button>
        );
      })}
      <button
        type="button"
        className={cn(
          "flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm transition-colors hover:bg-accent",
          value === null && "bg-accent"
        )}
        onClick={() => onChange(null)}
      >
        <span className={cn(
          "text-muted-foreground",
          value === null && "text-accent-foreground"
        )}>{t("anyRating")}</span>
      </button>
    </div>
  );
}
