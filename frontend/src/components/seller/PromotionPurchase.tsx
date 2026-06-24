"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Megaphone, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import type { PlacementPricing, ModelCatalogItem } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PLACEMENT_ICONS: Record<string, string> = {
  homepage_carousel: "homepageCarousel",
  category_spotlight: "categorySpotlight",
  search_boost: "searchBoost",
  promoted_badge: "promotedBadge",
};

interface PromotionPurchaseProps {
  models: ModelCatalogItem[];
  onPurchase?: () => void;
}

export function PromotionPurchase({ models, onPurchase }: PromotionPurchaseProps) {
  const t = useTranslations("seller.promotions");

  const [open, setOpen] = useState(false);
  const [pricing, setPricing] = useState<PlacementPricing[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedType, setSelectedType] = useState<string>("");
  const [selectedDuration, setSelectedDuration] = useState<number>(7);
  const [loading, setLoading] = useState(false);
  const [purchasing, setPurchasing] = useState(false);

  useEffect(() => {
    if (open) {
      setLoading(true);
      api
        .getPlacementPricing()
        .then(setPricing)
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [open]);

  const selectedPricing = pricing.find((p) => p.placement_type === selectedType);
  const selectedTier = selectedPricing?.tiers.find(
    (t) => t.duration_days === selectedDuration
  );

  const handlePurchase = async () => {
    if (!selectedModel || !selectedType || !selectedTier) return;
    setPurchasing(true);
    try {
      await api.purchasePlacement({
        catalog_model_id: selectedModel,
        placement_type: selectedType,
        duration_days: selectedDuration,
      });
      setOpen(false);
      setSelectedModel("");
      setSelectedType("");
      setSelectedDuration(7);
      onPurchase?.();
    } catch {
      // Error handled by API client
    } finally {
      setPurchasing(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <Megaphone className="w-4 h-4" />
          {t("promoteModel")}
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("selectModel")}</label>
              <Select value={selectedModel} onValueChange={setSelectedModel}>
                <SelectTrigger>
                  <SelectValue placeholder={t("selectModel")} />
                </SelectTrigger>
                <SelectContent>
                  {models.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">{t("placementType")}</label>
              <div className="grid grid-cols-2 gap-2">
                {pricing.map((p) => {
                  const nameKey = PLACEMENT_ICONS[p.placement_type] ?? p.placement_type;
                  const descKey = `${nameKey}Desc`;
                  return (
                    <button
                      key={p.placement_type}
                      onClick={() => setSelectedType(p.placement_type)}
                      className={`p-3 rounded-lg border text-left transition-colors ${
                        selectedType === p.placement_type
                          ? "border-primary bg-primary/5"
                          : "border-border hover:border-muted-foreground/50"
                      }`}
                    >
                      <p className="text-sm font-medium">{t(nameKey)}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {t(descKey)}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedPricing && (
              <div className="space-y-2">
                <label className="text-sm font-medium">{t("duration")}</label>
                <div className="flex gap-2">
                  {selectedPricing.tiers.map((tier) => (
                    <button
                      key={tier.duration_days}
                      onClick={() => setSelectedDuration(tier.duration_days)}
                      className={`flex-1 py-2 px-3 rounded-lg border text-center transition-colors ${
                        selectedDuration === tier.duration_days
                          ? "border-primary bg-primary/5"
                          : "border-border hover:border-muted-foreground/50"
                      }`}
                    >
                      <p className="text-sm font-medium">
                        {t(`days${tier.duration_days}`)}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {tier.credits_cost} {t("creditsCost")}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {selectedTier && (
              <div className="flex items-center justify-between pt-2 border-t">
                <div>
                  <p className="text-sm text-muted-foreground">{t("creditsCost")}</p>
                  <p className="text-lg font-semibold">
                    {selectedTier.credits_cost}{" "}
                    <span className="text-sm font-normal text-muted-foreground">
                      credits
                    </span>
                  </p>
                </div>
                <Button
                  onClick={handlePurchase}
                  disabled={!selectedModel || purchasing}
                  className="gap-2"
                >
                  {purchasing && <Loader2 className="w-4 h-4 animate-spin" />}
                  {t("purchase")}
                </Button>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
