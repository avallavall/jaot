import { useTranslations } from "next-intl";
import { Info } from "lucide-react";

export function SolverDisclaimer() {
  const t = useTranslations("public");

  return (
    <div className="mt-4 p-3 border rounded-md bg-muted/50 flex items-start gap-2">
      <Info className="w-4 h-4 text-muted-foreground shrink-0 mt-0.5" />
      <p className="text-xs text-muted-foreground">
        {t("solverDisclaimer")}
      </p>
    </div>
  );
}
