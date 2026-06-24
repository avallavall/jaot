"use client";

import { CircleCheck, CircleAlert, TriangleAlert } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useModelValidation } from "@/hooks/useModelValidation";
import { useTranslations } from "next-intl";
import type { HealthStatus, ValidationIssue } from "@/hooks/useModelValidation";

// Status dot color + icon map

const STATUS_CONFIG: Record<
  HealthStatus,
  { dotClass: string; icon: typeof CircleCheck; labelKey: string }
> = {
  valid: {
    dotClass: "bg-[var(--health-valid)]",
    icon: CircleCheck,
    labelKey: "valid",
  },
  warning: {
    dotClass: "bg-[var(--health-warning)]",
    icon: TriangleAlert,
    labelKey: "warning",
  },
  error: {
    dotClass: "bg-[var(--health-error)]",
    icon: CircleAlert,
    labelKey: "error",
  },
};

// Issue row

function IssueRow({
  issue,
  t,
}: {
  issue: ValidationIssue;
  t: ReturnType<typeof useTranslations>;
}) {
  const isError = issue.severity === "error";
  return (
    <li className="flex items-start gap-2 text-xs">
      <span
        className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
          isError ? "bg-[var(--health-error)]" : "bg-[var(--health-warning)]"
        }`}
      />
      <span className="text-muted-foreground">
        {t(issue.key, issue.params ?? {})}
      </span>
    </li>
  );
}

// Main component

export function ModelHealthBadge() {
  const t = useTranslations("builder.health");
  const { status, issues, errorCount, warningCount } = useModelValidation();
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;

  const issueCount = errorCount + warningCount;

  // Build the summary label shown next to the dot
  const summaryLabel =
    status === "valid"
      ? t("valid")
      : t("issueCount", { count: issueCount });

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t("ariaLabel", { status: t(config.labelKey) })}
        >
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${config.dotClass}`}
          />
          <span className="text-muted-foreground select-none">
            {summaryLabel}
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent align="start" className="w-72 p-3">
        <div className="flex items-center gap-2 mb-2">
          <Icon
            className={`h-4 w-4 ${
              status === "valid"
                ? "text-[var(--health-valid)]"
                : status === "warning"
                  ? "text-[var(--health-warning)]"
                  : "text-[var(--health-error)]"
            }`}
          />
          <span className="text-sm font-medium">{t("title")}</span>
        </div>

        {status === "valid" && (
          <p className="text-xs text-muted-foreground">{t("allGood")}</p>
        )}

        {issues.length > 0 && (
          <ul className="space-y-1.5">
            {issues.map((issue, idx) => (
              <IssueRow key={`${issue.key}-${idx}`} issue={issue} t={t} />
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
