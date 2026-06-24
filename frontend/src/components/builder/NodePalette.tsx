"use client";

import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useTranslations } from "next-intl";

interface PaletteItemProps {
  nodeType: string;
  label: string;
  description: string;
  colorClass: string;
  disabled?: boolean;
  disabledReason?: string;
}

function PaletteItem({
  nodeType,
  label,
  description,
  colorClass,
  disabled,
  disabledReason,
}: PaletteItemProps) {
  const handleDragStart = (event: React.DragEvent) => {
    if (disabled) return;
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <div
      draggable={!disabled}
      onDragStart={handleDragStart}
      title={disabled ? disabledReason : undefined}
      className={`
        mx-2 mb-2 p-2.5 border transition-all select-none
        ${
          disabled
            ? "border-border bg-muted opacity-40 cursor-not-allowed"
            : "border-transparent bg-card hover:border-primary hover:shadow-sm cursor-grab active:cursor-grabbing"
        }
      `}
    >
      <div className={`text-xs font-bold uppercase tracking-wider mb-0.5 ${colorClass}`}>
        {label}
      </div>
      <div className="text-[0.6875rem] text-muted-foreground leading-tight">{description}</div>
    </div>
  );
}

export function NodePalette() {
  const t = useTranslations("builder");
  const nodes = useBuilderStore((s) => s.nodes);
  const hasObjective = nodes.some((n) => n.type === "objective");

  return (
    <div className="w-48 border-r bg-background flex flex-col py-3 shrink-0" data-onboarding-target="palette">
      <div className="px-3 mb-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {t("palette.title")}
        </p>
      </div>

      <PaletteItem
        nodeType="variable"
        label={t("palette.variable")}
        description={t("palette.variableDescription")}
        colorClass="text-[var(--node-variable-selected)]"
      />

      <PaletteItem
        nodeType="constraint"
        label={t("palette.constraint")}
        description={t("palette.constraintDescription")}
        colorClass="text-[var(--node-constraint-selected)]"
      />

      <PaletteItem
        nodeType="objective"
        label={t("palette.objective")}
        description={t("palette.objectiveDescription")}
        colorClass="text-[var(--node-objective-selected)]"
        disabled={hasObjective}
        disabledReason={t("palette.objectiveDisabled")}
      />

      <div className="mt-auto px-3 pt-3 border-t">
        <p className="text-[0.625rem] text-muted-foreground leading-tight">
          {t("palette.dragHint")}
        </p>
      </div>
    </div>
  );
}
