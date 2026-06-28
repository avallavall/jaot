"use client";

import { Download, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { OptimizationProblem } from "@/lib/types";

interface ExportModelButtonProps {
  /** Lazily produce the problem to export; return null when there's nothing yet. */
  getProblem: () => OptimizationProblem | null;
  filenameBase?: string;
  disabled?: boolean;
  size?: "sm" | "default";
  variant?: "outline" | "ghost";
}

// Model formats only — sol/csv need a solution, so they live on the execution
// export, not here.
const MODEL_FORMATS = ["mps", "lp", "cip", "json"] as const;

/**
 * Export the current MODEL (no solve required) in a standard format.
 * Reusable across the visual builder, AI builder, etc. Calls the C2 endpoint
 * POST /api/v2/solve/export/model/{fmt} via api.fileExport.exportModel.
 */
export function ExportModelButton({
  getProblem,
  filenameBase = "model",
  disabled = false,
  size = "sm",
  variant = "outline",
}: ExportModelButtonProps) {
  const t = useTranslations("solve.export");

  const handleExport = async (fmt: (typeof MODEL_FORMATS)[number]) => {
    const problem = getProblem();
    if (!problem) {
      toast.error(t("downloadFailed"));
      return;
    }
    try {
      const blob = await api.fileExport.exportModel(problem, fmt);
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `${filenameBase}.${fmt}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
    } catch (err) {
      toast.error(getErrorMessage(err, t("downloadFailed")));
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={variant} size={size} disabled={disabled}>
          <Download className="h-4 w-4 mr-2" />
          {t("downloadModel")}
          <ChevronDown className="h-3 w-3 ml-1" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {MODEL_FORMATS.map((fmt) => (
          <DropdownMenuItem key={fmt} onClick={() => handleExport(fmt)}>
            {t(fmt)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
