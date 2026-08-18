"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { downloadCSV } from "@/lib/csv-utils";
import { downloadBlobAsFile } from "@/lib/download";
import { exportFilename } from "./export";

interface ComparisonExportButtonsProps {
  /** What the file should be called, before the timestamp and the extension. */
  base: string;
  /** Built on click, not on render: a matrix of sixty rows has no business
   *  being serialised on every poll tick while the grid is still filling. */
  rows: () => (string | number | null | undefined)[][];
  json: () => string;
}

/**
 * Take the table out of the page.
 *
 * Two formats because they answer different questions: CSV goes into a
 * spreadsheet or a report, JSON keeps every field for a script. Both are built
 * in the browser from data the page already has.
 *
 * Named for what it exports: `components/solve/ExportButtons` already exists
 * and exports a single execution's solution report, which is a different thing.
 */
export function ComparisonExportButtons({ base, rows, json }: ComparisonExportButtonsProps) {
  const t = useTranslations("solverCompare");

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-2"
        // downloadCSV rather than a local writer: it quotes per RFC 4180 and
        // prefixes the UTF-8 BOM that makes Excel read a dataset named
        // "Producción" correctly instead of as mojibake.
        onClick={() => downloadCSV(exportFilename(base, "csv"), rows())}
      >
        <Download className="h-3.5 w-3.5" />
        {t("export.csv")}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-2"
        onClick={() =>
          downloadBlobAsFile(
            new Blob([json()], { type: "application/json;charset=utf-8" }),
            exportFilename(base, "json"),
          )
        }
      >
        <Download className="h-3.5 w-3.5" />
        {t("export.json")}
      </Button>
    </div>
  );
}
