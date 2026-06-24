"use client";

import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { CreditPool } from "@/lib/types";
import { usePermission } from "@/hooks/usePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTranslations } from "next-intl";
import { Coins } from "lucide-react";

interface CreditPoolCardProps {
  workspaceId: string;
  pool: CreditPool | null;
  onPoolChange?: (pool: CreditPool) => void;
}

function getProgressColor(percent: number): string {
  if (percent >= 90) return "bg-red-500";
  if (percent >= 70) return "bg-yellow-500";
  return "bg-green-500";
}

export function CreditPoolCard({ workspaceId, pool, onPoolChange }: CreditPoolCardProps) {
  const isAdmin = usePermission("admin");
  const roleName = useRoleDisplayName();
  const t = useTranslations("workspace.creditPool");
  const tc = useTranslations("common");
  const [allocateOpen, setAllocateOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [allocating, setAllocating] = useState(false);

  const handleAllocate = async () => {
    const numAmount = parseInt(amount, 10);
    if (isNaN(numAmount) || numAmount <= 0) {
      toast.error(t("allocateError"));
      return;
    }
    setAllocating(true);
    try {
      const updated = await api.allocateCredits(workspaceId, numAmount);
      onPoolChange?.(updated);
      toast.success(t("allocateSuccess", { amount: numAmount }));
      setAmount("");
      setAllocateOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("allocateFailed"));
    } finally {
      setAllocating(false);
    }
  };

  if (!pool) {
    return (
      <div className="border rounded-lg p-6 bg-card">
        <div className="flex items-center gap-2 mb-4">
          <Coins className="w-5 h-5 text-primary" />
          <h3 className="font-semibold">{t("title")}</h3>
        </div>
        <p className="text-sm text-muted-foreground">{t("noPool")}</p>
        {isAdmin && (
          <TooltipProvider>
            <div className="mt-4">
              <Button size="sm" onClick={() => setAllocateOpen(true)}>
                {t("allocateCredits")}
              </Button>
            </div>
          </TooltipProvider>
        )}
        {allocateOpen && (
          <AllocateForm
            t={t}
            tc={tc}
            amount={amount}
            setAmount={setAmount}
            allocating={allocating}
            onAllocate={handleAllocate}
            onCancel={() => setAllocateOpen(false)}
          />
        )}
      </div>
    );
  }

  const usedPercent =
    pool.allocated_credits > 0
      ? Math.min(100, Math.round((pool.used_credits / pool.allocated_credits) * 100))
      : 0;

  return (
    <TooltipProvider>
      <div className="border rounded-lg p-6 bg-card">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Coins className="w-5 h-5 text-primary" />
            <h3 className="font-semibold">{t("title")}</h3>
          </div>
          {isAdmin ? (
            <Button size="sm" variant="outline" onClick={() => setAllocateOpen(!allocateOpen)}>
              {allocateOpen ? tc("cancel") : t("allocateCredits")}
            </Button>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button size="sm" variant="outline" disabled>
                    {t("allocateCredits")}
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs text-center">
                {t("adminRequired", { role: roleName })}
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        <div className="grid grid-cols-3 gap-4 mb-4">
          <div>
            <p className="text-xs text-muted-foreground">{t("allocated")}</p>
            <p className="text-xl font-bold">{pool.allocated_credits.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t("used")}</p>
            <p className="text-xl font-bold">{pool.used_credits.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t("available")}</p>
            <p className="text-xl font-bold text-primary">{pool.available_credits.toLocaleString()}</p>
          </div>
        </div>

        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{t("percentUsed", { percent: usedPercent })}</span>
            <span>{t("remaining", { count: pool.available_credits.toLocaleString() })}</span>
          </div>
          <div className="w-full bg-muted rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${getProgressColor(usedPercent)}`}
              style={{ width: `${usedPercent}%` }}
            />
          </div>
        </div>

        {allocateOpen && isAdmin && (
          <AllocateForm
            t={t}
            tc={tc}
            amount={amount}
            setAmount={setAmount}
            allocating={allocating}
            onAllocate={handleAllocate}
            onCancel={() => setAllocateOpen(false)}
          />
        )}
      </div>
    </TooltipProvider>
  );
}

function AllocateForm({
  t,
  tc,
  amount,
  setAmount,
  allocating,
  onAllocate,
  onCancel,
}: {
  t: ReturnType<typeof useTranslations>;
  tc: ReturnType<typeof useTranslations>;
  amount: string;
  setAmount: (v: string) => void;
  allocating: boolean;
  onAllocate: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="mt-4 p-4 border rounded-md bg-muted/30 space-y-3">
      <div className="space-y-1">
        <Label>{t("amountLabel")}</Label>
        <Input
          type="number"
          min={1}
          placeholder={t("amountPlaceholder")}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAllocate()}
        />
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={onAllocate} disabled={allocating || !amount}>
          {allocating ? t("allocating") : t("confirm")}
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>
          {tc("cancel")}
        </Button>
      </div>
    </div>
  );
}
