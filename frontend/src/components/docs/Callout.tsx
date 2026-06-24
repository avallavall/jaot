import { Lightbulb, AlertTriangle, Info, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type CalloutType = "tip" | "warning" | "info" | "danger";

interface CalloutProps {
  type?: CalloutType;
  children: React.ReactNode;
}

const iconMap = {
  tip: Lightbulb,
  warning: AlertTriangle,
  info: Info,
  danger: AlertCircle,
};

const styleMap = {
  tip: "border-green-500/40 bg-green-50 text-green-900 dark:bg-green-950/30 dark:text-green-200",
  warning:
    "border-amber-500/40 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200",
  info: "border-blue-500/40 bg-blue-50 text-blue-900 dark:bg-blue-950/30 dark:text-blue-200",
  danger:
    "border-red-500/40 bg-red-50 text-red-900 dark:bg-red-950/30 dark:text-red-200",
};

const iconColorMap = {
  tip: "text-green-600 dark:text-green-400",
  warning: "text-amber-600 dark:text-amber-400",
  info: "text-blue-600 dark:text-blue-400",
  danger: "text-red-600 dark:text-red-400",
};

export function Callout({ type = "info", children }: CalloutProps) {
  const Icon = iconMap[type];
  return (
    <div
      className={cn(
        "my-4 flex gap-3 rounded-lg border p-4",
        styleMap[type]
      )}
    >
      <Icon className={cn("h-5 w-5 mt-0.5 shrink-0", iconColorMap[type])} />
      <div className="flex-1 text-sm [&>p]:m-0">{children}</div>
    </div>
  );
}
