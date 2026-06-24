"use client";

import { Sparkles, TrendingUp, Terminal } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SkillLevel } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SkillLevelSelectorProps {
  value: SkillLevel;
  onChange: (level: SkillLevel) => void;
}

export function SkillLevelSelector({ value, onChange }: SkillLevelSelectorProps) {
  const t = useTranslations("common");

  const OPTIONS: {
    value: SkillLevel;
    label: string;
    subtext: string;
    icon: React.ReactNode;
  }[] = [
    {
      value: "beginner",
      label: t("guidance.skillBeginner"),
      subtext: t("guidance.skillBeginnerSubtext"),
      icon: <Sparkles className="h-5 w-5" />,
    },
    {
      value: "intermediate",
      label: t("guidance.skillIntermediate"),
      subtext: t("guidance.skillIntermediateSubtext"),
      icon: <TrendingUp className="h-5 w-5" />,
    },
    {
      value: "expert",
      label: t("guidance.skillExpert"),
      subtext: t("guidance.skillExpertSubtext"),
      icon: <Terminal className="h-5 w-5" />,
    },
  ];

  return (
    <div className="space-y-3">
      {OPTIONS.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              "w-full flex items-center gap-4 rounded-lg border-2 p-4 text-left transition-colors",
              selected
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/40"
            )}
          >
            <span
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                selected
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {opt.icon}
            </span>
            <div>
              <div className="font-medium">{opt.label}</div>
              <div className="text-sm text-muted-foreground">{opt.subtext}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
