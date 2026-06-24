"use client";

import { useState } from "react";
import { CreditCard, Coins, ArrowRight, ShoppingCart } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";

const TOPUP_PACKS = [
  { credits: 500, price: 14, pricePerCredit: 0.028 },
  { credits: 2000, price: 48, pricePerCredit: 0.024 },
  { credits: 5000, price: 100, pricePerCredit: 0.020 },
  { credits: 20000, price: 320, pricePerCredit: 0.016 },
] as const;

export default function BillingPage() {
  const { organization } = useAuth();
  const t = useTranslations("billing");
  const [purchasing, setPurchasing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const planName = organization?.plan
    ? organization.plan.charAt(0).toUpperCase() + organization.plan.slice(1)
    : "Free";
  const isFree = !organization?.plan || organization.plan === "free";

  const handleTopup = async (credits: number) => {
    setPurchasing(credits);
    setError(null);
    try {
      const result = await api.createTopupCheckout({
        credits,
        success_url: `${window.location.origin}/workspace/credits?topup=success`,
        cancel_url: `${window.location.origin}/billing?topup=cancelled`,
      });
      if (result.checkout_url) {
        // eslint-disable-next-line react-hooks/immutability
        window.location.href = result.checkout_url;
      }
    } catch (err) {
      // User-safe, localized fallback — never leak internal diagnostics like
      // "Is Stripe configured?" (audit F-13/F-10; BYO-Stripe deployments will
      // legitimately run without payments).
      setError(getErrorMessage(err, t("checkoutUnavailable")));
      setPurchasing(null);
    }
  };

  return (
    <>
      <h1 className="text-2xl font-bold tracking-tight mb-6">{t("title")}</h1>

      <div className="grid gap-4 sm:grid-cols-2 max-w-3xl">
        <div className="rounded-lg border bg-card p-6">
          <div className="flex items-center gap-3 mb-3">
            <CreditCard className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-sm font-medium text-muted-foreground">{t("currentPlan")}</h2>
          </div>
          <p className="text-2xl font-semibold">{planName}</p>
        </div>

        <div className="rounded-lg border bg-card p-6">
          <div className="flex items-center gap-3 mb-3">
            <Coins className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-sm font-medium text-muted-foreground">{t("creditBalance")}</h2>
          </div>
          <p className="text-2xl font-semibold">
            {organization?.credits_balance?.toLocaleString() ?? 0}
          </p>
        </div>
      </div>

      <div className="mt-6 max-w-3xl">
        <div className="flex items-center gap-3 mb-4">
          <ShoppingCart className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">{t("buyCredits")}</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          {t("topupDescription")}
        </p>
        {error && (
          <div className="mb-4 p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
            {error}
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {TOPUP_PACKS.map((pack) => (
            <button
              key={pack.credits}
              onClick={() => handleTopup(pack.credits)}
              disabled={purchasing !== null}
              className="rounded-lg border bg-card p-5 text-left hover:border-primary hover:shadow-sm transition-all disabled:opacity-50"
            >
              <div className="text-2xl font-bold text-primary">
                {pack.credits.toLocaleString()}
              </div>
              <div className="text-sm text-muted-foreground mb-3">{t("creditsUnit")}</div>
              <div className="text-xl font-semibold">
                {t("priceEur", { price: pack.price })}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                {pack.pricePerCredit} {t("eurPerCredit")}
              </div>
              {purchasing === pack.credits && (
                <div className="mt-2 text-xs text-primary animate-pulse">
                  {t("redirectingToStripe")}
                </div>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 rounded-lg border bg-card p-6 max-w-3xl">
        {isFree ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {t.rich("freePlanUpgrade", { strong: (chunks) => <strong>{chunks}</strong> })}
            </p>
            <a
              href="mailto:sales@jaot.io"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
            >
              {t("contactUpgrade")} <ArrowRight className="h-3.5 w-3.5" />
            </a>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t.rich("managedPlanMessage", {
              planName,
              strong: (chunks) => <strong>{chunks}</strong>,
              link: (chunks) => (
                <a href="mailto:support@jaot.io" className="text-primary underline hover:opacity-80">
                  {chunks}
                </a>
              ),
            })}
          </p>
        )}
      </div>
    </>
  );
}
