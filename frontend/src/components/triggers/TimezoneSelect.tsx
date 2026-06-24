"use client";

import { useState, useMemo } from "react";
import { useTranslations } from "next-intl";
import { getGroupedTimezones, getBrowserTimezone } from "@/lib/cron-utils";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface TimezoneSelectProps {
  value: string;
  onChange: (tz: string) => void;
  disabled?: boolean;
}

function getUtcOffset(tz: string): string {
  try {
    const formatted = new Intl.DateTimeFormat("en", {
      timeZone: tz,
      timeZoneName: "shortOffset",
    }).format(new Date());
    // Extract the offset part (e.g., "GMT-5" from "1/1/2024, GMT-5")
    const match = formatted.match(/(GMT[+-]?\d*:?\d*)/);
    return match ? match[1] : "";
  } catch {
    return "";
  }
}

export function TimezoneSelect({ value, onChange, disabled }: TimezoneSelectProps) {
  const t = useTranslations("triggers.schedule");
  const [search, setSearch] = useState("");
  const grouped = useMemo(() => getGroupedTimezones(), []);
  const defaultValue = value || getBrowserTimezone();

  const filteredGroups = useMemo(() => {
    const lowerSearch = search.toLowerCase();
    if (!lowerSearch) return grouped;

    const result: Record<string, string[]> = {};
    for (const [region, tzList] of Object.entries(grouped)) {
      const filtered = tzList.filter((tz) =>
        tz.toLowerCase().includes(lowerSearch)
      );
      if (filtered.length > 0) {
        result[region] = filtered;
      }
    }
    return result;
  }, [grouped, search]);

  const sortedRegions = useMemo(
    () => Object.keys(filteredGroups).sort(),
    [filteredGroups]
  );

  return (
    <Select value={defaultValue} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="w-full">
        <SelectValue placeholder={t("selectTimezone")} />
      </SelectTrigger>
      <SelectContent className="max-h-72">
        <div className="p-2 sticky top-0 bg-popover">
          <input
            type="text"
            placeholder={t("searchTimezones")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          />
        </div>
        {sortedRegions.map((region) => (
          <SelectGroup key={region}>
            <SelectLabel>{region}</SelectLabel>
            {filteredGroups[region].map((tz) => (
              <SelectItem key={tz} value={tz}>
                <span className="flex items-center justify-between gap-2 w-full">
                  <span>{tz.replace(/_/g, " ")}</span>
                  <span className="text-xs text-muted-foreground ml-2">
                    {getUtcOffset(tz)}
                  </span>
                </span>
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
        {sortedRegions.length === 0 && (
          <div className="py-4 text-center text-sm text-muted-foreground">
            {t("noTimezonesFound")}
          </div>
        )}
      </SelectContent>
    </Select>
  );
}
