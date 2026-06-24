"use client";

import { useTranslations } from "next-intl";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";

interface PriceRangeFilterProps {
  min: number;
  max: number;
  value: [number | null, number | null];
  onChange: (value: [number | null, number | null]) => void;
}

export function PriceRangeFilter({
  min,
  max,
  value,
  onChange,
}: PriceRangeFilterProps) {
  const t = useTranslations("marketplace.filters");

  const currentMin = value[0] ?? min;
  const currentMax = value[1] ?? max;
  const isActive = value[0] !== null || value[1] !== null;

  return (
    <div className="space-y-3">
      <Slider
        min={min}
        max={max}
        step={1}
        value={[currentMin, currentMax]}
        onValueChange={(vals: number[]) => {
          const newMin = vals[0];
          const newMax = vals[1];
          // If at extremes, treat as "no filter"
          if (newMin <= min && newMax >= max) {
            onChange([null, null]);
          } else {
            onChange([newMin, newMax]);
          }
        }}
      />
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{t("priceCredits", { value: currentMin })}</span>
        <span>{t("priceCredits", { value: currentMax })}</span>
      </div>
      {isActive && (
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs"
          onClick={() => onChange([null, null])}
        >
          {t("clearPrice")}
        </Button>
      )}
    </div>
  );
}
