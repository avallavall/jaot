"use client";

import { useMemo } from "react";
import { DAYS_ORDERED } from "@/lib/cron-utils";

interface DayOfWeekPickerProps {
  selected: string[];
  onChange: (days: string[]) => void;
  locale: string;
  disabled?: boolean;
}

export function DayOfWeekPicker({ selected, onChange, locale, disabled }: DayOfWeekPickerProps) {
  // Derive localized day labels from Intl (2024-01-01 is a Monday)
  const dayLabels = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(locale, { weekday: "short" });
    const baseMonday = new Date(2024, 0, 1); // Monday
    return DAYS_ORDERED.map((_, i) => {
      const date = new Date(baseMonday);
      date.setDate(baseMonday.getDate() + i);
      return formatter.format(date);
    });
  }, [locale]);

  const toggleDay = (day: string) => {
    if (disabled) return;
    if (selected.includes(day)) {
      onChange(selected.filter((d) => d !== day));
    } else {
      onChange([...selected, day]);
    }
  };

  return (
    <div className="flex gap-1.5 flex-wrap">
      {DAYS_ORDERED.map((day, i) => {
        const isSelected = selected.includes(day);
        return (
          <button
            key={day}
            type="button"
            disabled={disabled}
            onClick={() => toggleDay(day)}
            className={`w-10 h-10 rounded-lg text-sm font-medium transition-colors ${
              isSelected
                ? "bg-primary text-primary-foreground"
                : "bg-muted hover:bg-muted/80 text-foreground"
            } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            aria-pressed={isSelected}
            aria-label={dayLabels[i]}
          >
            {dayLabels[i]}
          </button>
        );
      })}
    </div>
  );
}
