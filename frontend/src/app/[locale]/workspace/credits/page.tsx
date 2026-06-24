"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  api,
  CreditTransaction,
  Withdrawal,
  WithdrawalSchedule,
  CreditSettings
} from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";

// Extended balance type — API returns the three-pool credit model
interface CreditBalance {
  credits_balance: number;
  credits_subscription: number;
  credits_purchased: number;
  credits_earned: number;
  credits_used_month?: number;
  plan?: string;
  monthly_limit?: number;
  exchange_rate?: number;
  local_balance?: number;
  local_earned?: number;
  currency?: string;
}
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDialog } from "@/components/ui/dialog-custom";
import { ConceptTooltip } from "@/components/ui/concept-tooltip";
import { EmptyState } from "@/components/guidance/EmptyState";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Coins } from "lucide-react";

const CURRENCIES = [
  { code: "EUR", symbol: "€", name: "Euro" },
  { code: "USD", symbol: "$", name: "US Dollar" },
  { code: "GBP", symbol: "£", name: "British Pound" },
  { code: "CHF", symbol: "Fr", name: "Swiss Franc" },
];

const FREQUENCY_KEYS = ["weekly", "biweekly", "monthly", "quarterly"] as const;
const AMOUNT_TYPE_KEYS = ["all", "percentage", "fixed"] as const;

export default function CreditsPage() {
  const router = useRouter();
  const dialog = useDialog();
  const t = useTranslations("workspace.credits");
  const tc = useTranslations("common");
  const { transactionTypeLabel } = useCommonLabels();
  
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
  const [schedules, setSchedules] = useState<WithdrawalSchedule[]>([]);
  const [, setSettings] = useState<CreditSettings | null>(null);
  const [loading, setLoading] = useState(true);
  
  // Forms
  const [withdrawAmount, setWithdrawAmount] = useState("");
  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [scheduleForm, setScheduleForm] = useState({
    frequency: "monthly",
    amount_type: "all",
    amount_value: "",
    min_threshold: "100",
  });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      // Load each independently to handle partial failures
      const [balanceData, settingsData] = await Promise.all([
        (api.getCreditBalance() as Promise<CreditBalance>).catch(() => null),
        api.getCreditSettings().catch(() => null),
      ]);
      
      if (balanceData) setBalance(balanceData);
      if (settingsData) {
        setSettings(settingsData);
      }
      
      // Load these separately as they might fail on fresh installs
      try {
        const txData = await api.getCreditTransactions({ limit: 20 });
        setTransactions(txData || []);
      } catch {
        setTransactions([]);
      }
      
      try {
        const withdrawData = await api.getWithdrawals();
        setWithdrawals(withdrawData || []);
      } catch {
        setWithdrawals([]);
      }
      
      try {
        const scheduleData = await api.getWithdrawalSchedules();
        setSchedules(scheduleData || []);
      } catch {
        setSchedules([]);
      }
    } catch (err) {
      console.warn('Failed to load credit data:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleWithdraw = async () => {
    const amount = parseInt(withdrawAmount);
    if (!amount || amount <= 0) {
      dialog.showError(t("invalidAmount"));
      return;
    }
    
    const confirmed = await dialog.confirm(
      t("withdrawConfirmMessage", { amount, currencySymbol: getCurrencySymbol(), fiatAmount: ((amount / 10) * (balance?.exchange_rate || 1)).toFixed(2) }),
      t("confirmWithdrawal")
    );
    
    if (!confirmed) return;
    
    try {
      await api.createWithdrawal({ credits_amount: amount, currency: balance?.currency || "EUR" });
      dialog.showSuccess(t("withdrawalSuccess"));
      setWithdrawAmount("");
      loadData();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedWithdrawal")));
    }
  };

  const handleChangeCurrency = async (currency: string) => {
    try {
      await api.updateCurrency({ currency });
      loadData();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedCurrencyUpdate")));
    }
  };

  const handleCreateSchedule = async () => {
    try {
      await api.createWithdrawalSchedule({
        frequency: scheduleForm.frequency,
        amount_type: scheduleForm.amount_type,
        amount_value: scheduleForm.amount_type !== "all" ? parseFloat(scheduleForm.amount_value) : undefined,
        min_threshold: parseInt(scheduleForm.min_threshold) || 100,
      });
      dialog.showSuccess(t("scheduleSaved"));
      setShowScheduleForm(false);
      loadData();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedCreateSchedule")));
    }
  };

  const handleDeleteSchedule = async (id: string) => {
    const confirmed = await dialog.confirm(t("deleteScheduleConfirm"), tc("confirm"));
    if (!confirmed) return;

    try {
      await api.deleteWithdrawalSchedule(id);
      loadData();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedDeleteSchedule")));
    }
  };

  const getCurrencySymbol = () => {
    return CURRENCIES.find(c => c.code === balance?.currency)?.symbol || "€";
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed": return "text-green-600 bg-green-100";
      case "pending": return "text-yellow-600 bg-yellow-100";
      case "processing": return "text-blue-600 bg-blue-100";
      case "failed": return "text-red-600 bg-red-100";
      default: return "text-gray-600 bg-gray-100";
    }
  };

  const getTxTypeColor = (type: string) => {
    if (type.includes("earning") || type === "purchase" || type === "bonus" || type === "refund") {
      return "text-green-600";
    }
    return "text-red-600";
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8" aria-busy="true">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3"></div>
          <div className="h-64 bg-muted rounded"></div>
        </div>
        <div aria-live="polite" className="sr-only">{t("loadingCredits")}</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="mb-6">
        <Link href="/workspace" className="text-sm text-muted-foreground hover:text-foreground">
          {t("backToWorkspace")}
        </Link>
      </div>
      
      <h1 className="text-3xl font-bold text-foreground mb-8">{t("title")}</h1>

      <div className="bg-card border rounded-lg p-6 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-muted-foreground mb-1">{t("totalBalance")}</div>
            <div className="text-4xl font-bold text-primary">
              {balance?.credits_balance.toLocaleString()} <span className="text-xl">{t("credits")}</span>
            </div>
            <div className="text-sm text-muted-foreground mt-1">
              ≈ {getCurrencySymbol()}{balance?.local_balance?.toFixed(2) ?? "0.00"}
            </div>
          </div>
          <Button
            size="lg"
            onClick={() => router.push("/billing?action=topup")}
            className="ml-4"
          >
            + {t("buyCredits")}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-card border rounded-lg p-5">
          <div className="text-sm text-muted-foreground mb-1">
            {t("subscriptionCredits")}
          </div>
          <div className="text-2xl font-bold text-foreground">
            {(balance?.credits_subscription ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            {t("subscriptionCreditsNote")}
          </div>
        </div>

        <div className="bg-card border rounded-lg p-5">
          <div className="text-sm text-muted-foreground mb-1">
            {t("purchasedCredits")}
          </div>
          <div className="text-2xl font-bold text-blue-600">
            {(balance?.credits_purchased ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            {t("purchasedCreditsNote")}
          </div>
        </div>

        <div className="bg-card border rounded-lg p-5">
          <div className="text-sm text-muted-foreground mb-1">
            {t("earnedCredits")}
          </div>
          <div className="text-2xl font-bold text-green-600">
            {(balance?.credits_earned ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            {t("earnedCreditsNote")}
          </div>
          {(balance?.credits_earned ?? 0) > 0 && (
            <Link
              href="/workspace/credits/seller-earnings"
              className="inline-block mt-2 text-sm text-primary hover:underline font-medium"
            >
              {t("viewSellerEarnings")}
            </Link>
          )}
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6 mb-8">
        <h2 className="text-lg font-semibold mb-3">{t("howCalculated")}</h2>
        <p className="text-sm text-muted-foreground mb-3">
          {t("calculatedDescriptionSqrt")}
        </p>
        <div className="flex flex-wrap gap-3 text-sm">
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="base-cost">{t("baseCost")}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="variable-cost">{"sqrt(vars)"}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="integer-penalty">{"sqrt(MIP)"}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="constraint-cost">{"sqrt(constraints)"}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="time-bonus">{t("timeBonus")}</ConceptTooltip>
          </span>
        </div>
        <div className="mt-3 px-3 py-2 bg-primary/5 border border-primary/20 rounded-md text-sm text-primary">
          {t("maxCreditsNote")}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">{t("currency")}</h2>
          <div className="flex gap-2">
            {CURRENCIES.map((curr) => (
              <button
                key={curr.code}
                onClick={() => handleChangeCurrency(curr.code)}
                className={`px-4 py-2 rounded-lg border transition-colors ${
                  balance?.currency === curr.code
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border hover:border-primary/50"
                }`}
              >
                {curr.symbol} {curr.code}
              </button>
            ))}
          </div>
        </div>

        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">{t("bankDetails")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("paymentSettingsStripe")}
          </p>
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">{t("withdrawCredits")}</h2>
        <div className="flex gap-4 items-end">
          <div className="flex-1">
            <label htmlFor="credits-withdraw-amount" className="block text-sm text-muted-foreground mb-1">{t("amountCredits")}</label>
            <Input
              id="credits-withdraw-amount"
              type="number"
              placeholder={t("enterAmount")}
              value={withdrawAmount}
              onChange={(e) => setWithdrawAmount(e.target.value)}
              max={balance?.credits_earned}
            />
            <p className="text-xs text-muted-foreground mt-1">
              {t("maxCredits", { count: balance?.credits_earned.toLocaleString() ?? "0" })}
            </p>
          </div>
          <div className="text-center px-4">
            <div className="text-2xl">→</div>
          </div>
          <div className="flex-1">
            <label htmlFor="credits-receive-amount" className="block text-sm text-muted-foreground mb-1">{t("youReceive")}</label>
            <div className="text-2xl font-bold">
              {getCurrencySymbol()}
              {withdrawAmount ? ((parseInt(withdrawAmount) / 10) * (balance?.exchange_rate || 1)).toFixed(2) : "0.00"}
            </div>
          </div>
          <Button onClick={handleWithdraw} disabled={!withdrawAmount || parseInt(withdrawAmount) <= 0}>
            {t("withdraw")}
          </Button>
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{t("scheduledWithdrawals")}</h2>
          <Button variant="outline" size="sm" onClick={() => setShowScheduleForm(!showScheduleForm)}>
            {t("addSchedule")}
          </Button>
        </div>
        
        {showScheduleForm && (
          <div className="bg-muted/30 rounded-lg p-4 mb-4 space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="schedule-frequency" className="block text-sm mb-1">{t("frequency")}</label>
                <select
                  id="schedule-frequency"
                  value={scheduleForm.frequency}
                  onChange={(e) => setScheduleForm({ ...scheduleForm, frequency: e.target.value })}
                  className="w-full px-3 py-2 rounded-md border bg-background"
                >
                  {FREQUENCY_KEYS.map((f) => (
                    <option key={f} value={f}>{t(`frequencies.${f}`)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="schedule-amount-type" className="block text-sm mb-1">{t("amountType")}</label>
                <select
                  id="schedule-amount-type"
                  value={scheduleForm.amount_type}
                  onChange={(e) => setScheduleForm({ ...scheduleForm, amount_type: e.target.value })}
                  className="w-full px-3 py-2 rounded-md border bg-background"
                >
                  {AMOUNT_TYPE_KEYS.map((at) => (
                    <option key={at} value={at}>{t(`amountTypes.${at}`)}</option>
                  ))}
                </select>
              </div>
            </div>
            {scheduleForm.amount_type !== "all" && (
              <Input
                type="number"
                placeholder={scheduleForm.amount_type === "percentage" ? t("percentagePlaceholder") : t("fixedPlaceholder")}
                value={scheduleForm.amount_value}
                onChange={(e) => setScheduleForm({ ...scheduleForm, amount_value: e.target.value })}
              />
            )}
            <Input
              type="number"
              placeholder={t("minThresholdPlaceholder")}
              value={scheduleForm.min_threshold}
              onChange={(e) => setScheduleForm({ ...scheduleForm, min_threshold: e.target.value })}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleCreateSchedule}>{t("createSchedule")}</Button>
              <Button size="sm" variant="outline" onClick={() => setShowScheduleForm(false)}>{tc("cancel")}</Button>
            </div>
          </div>
        )}
        
        {schedules.length > 0 ? (
          <div className="space-y-2">
            {schedules.map((schedule) => {
              const s = schedule as unknown as Record<string, unknown>;
              return (
              <div key={schedule.id} className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                <div>
                  <div className="font-medium capitalize">{schedule.frequency}</div>
                  <div className="text-sm text-muted-foreground">
                    {s.amount_type === "all"
                      ? t("allCredits")
                      : s.amount_type === "percentage"
                        ? `${s.amount_value}%`
                        : t("amountCreditsFixed", { value: String(s.amount_value) })
                    }
                    {" · "}{t("minThreshold", { threshold: String(s.min_threshold ?? 0) })}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Next: {new Date(schedule.next_execution).toLocaleDateString()}
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => handleDeleteSchedule(schedule.id)}>
                  🗑️
                </Button>
              </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("noSchedules")}</p>
        )}
      </div>

      <div className="bg-card border rounded-lg p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">{t("recentWithdrawals")}</h2>
        {withdrawals.length > 0 ? (
          <div className="space-y-2">
            {withdrawals.map((w) => {
              const wExt = w as unknown as Record<string, unknown>;
              return (
              <div key={w.id} className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                <div>
                  <div className="font-medium">
                    {w.credits_amount.toLocaleString()} credits → {getCurrencySymbol()}{w.amount_fiat.toFixed(2)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(w.created_at).toLocaleString()}{wExt.withdrawal_type ? ` · ${wExt.withdrawal_type}` : ""}
                  </div>
                </div>
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(w.status)}`}>
                  {w.status}
                </span>
              </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("noWithdrawals")}</p>
        )}
      </div>

      <div className="bg-card border rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">{t("transactionHistory")}</h2>
        {transactions.length > 0 ? (
          <div className="space-y-2">
            {transactions.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between p-3 border-b last:border-0">
                <div>
                  <div className="font-medium">{tx.description || t("creditTransaction")}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(tx.created_at).toLocaleString()} · {transactionTypeLabel(tx.transaction_type || "purchase")}
                  </div>
                </div>
                <div className={`font-mono font-medium ${getTxTypeColor(tx.transaction_type || "purchase")}`}>
                  {tx.credits_amount != null ? (
                    <>
                      {tx.credits_amount > 0 ? "+" : ""}{tx.credits_amount.toLocaleString()}
                    </>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Coins className="h-12 w-12" />}
            title={t("noActivityTitle")}
            description={t("noActivityDescription")}
            expertDescription={t("noActivityExpert")}
            actionLabel={t("viewPricing")}
            actionHref="/marketplace"
          />
        )}
      </div>

      <dialog.DialogComponent />
    </div>
  );
}
