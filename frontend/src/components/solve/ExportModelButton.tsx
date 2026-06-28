"use client";

import { useState } from "react";
import { Download, ChevronDown, Loader2 } from "lucide-react";
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
import { downloadBlobAsFile } from "@/lib/download";
import { getErrorMessage } from "@/lib/errors";
import type { OptimizationProblem } from "@/lib/types";

/**
 * Produce the problem to export. May be synchronous (builder canvas / AI
 * formulation already hold the problem) or async (template/model surfaces that
 * must render the problem via a preview call first). Returns null when there's
 * nothing exportable yet.
 */
type ProblemProvider = () =>
  | OptimizationProblem
  | null
  | Promise<OptimizationProblem | null>;

interface ExportModelButtonProps {
  getProblem: ProblemProvider;
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
  const [busy, setBusy] = useState(false);

  const handleExport = async (fmt: (typeof MODEL_FORMATS)[number]) => {
    setBusy(true);
    try {
      // getProblem may run a preview call (template/model surfaces), so await it.
      const problem = await getProblem();
      if (!problem) {
        toast.error(t("downloadFailed"));
        return;
      }
      const blob = await api.fileExport.exportModel(problem, fmt);
      downloadBlobAsFile(blob, `${filenameBase}.${fmt}`);
    } catch (err) {
      toast.error(getErrorMessage(err, t("downloadFailed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={variant} size={size} disabled={disabled || busy}>
          {busy ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Download className="h-4 w-4 mr-2" />
          )}
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
