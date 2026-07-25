"use client";

import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";

interface AdvancedModelToggleProps {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Ask the assistant to answer with the advanced model.
 *
 * Deliberately a plain opt-in rather than a model picker: the platform decides
 * WHICH models back each tier (they change), the user decides how much thinking
 * this particular question is worth. The hint names the trade-off — slower and
 * more expensive — because the cost is real and lands on the org's budget.
 */
export function AdvancedModelToggle({
  checked,
  onChange,
  disabled,
  className = "",
}: AdvancedModelToggleProps) {
  const t = useTranslations("llm.modelChoice");
  return (
    <label
      className={`inline-flex cursor-pointer items-center gap-1.5 text-xs ${className}`}
      title={t("hint")}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-primary h-3.5 w-3.5"
        data-testid="advanced-model-toggle"
      />
      <Sparkles className="h-3 w-3 text-muted-foreground" aria-hidden />
      <span className="whitespace-nowrap text-muted-foreground">{t("advanced")}</span>
    </label>
  );
}
