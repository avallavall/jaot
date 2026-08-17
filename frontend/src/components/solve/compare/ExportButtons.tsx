"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { downloadText, exportFilename } from "./export";

interface ExportButtonsProps {
  /** What the file should be called, before the timestamp and the extension. */
  base: string;
  /** Built on click, not on render: a matrix of sixty rows has no business
   *  being serialised on every poll tick while the grid is still filling. */
  csv: () => string;
  json: () => string;
}

/**
 * Take the table out of the page.
 *
 * Two formats because they answer different questions: CSV goes into a
 * spreadsheet or a report, JSON keeps every field for a script. Both are built
 * in the browser from data the page already has.
 */
export function ExportButtons({ base, csv, json }: ExportButtonsProps) {
  const t = useTranslations("solverCompare");

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-2"
        onClick={() => downloadText(exportFilename(base, "csv"), "text/csv", csv())}
      >
        <Download className="h-3.5 w-3.5" />
        {t("export.csv")}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-2"
        onClick={() => downloadText(exportFilename(base, "json"), "application/json", json())}
      >
        <Download className="h-3.5 w-3.5" />
        {t("export.json")}
      </Button>
    </div>
  );
}
