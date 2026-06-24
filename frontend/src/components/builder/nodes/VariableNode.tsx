"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps, Node } from "@xyflow/react";
import type { VariableNodeData } from "@/lib/builder/types";
import { useTranslations } from "next-intl";

const TYPE_COLORS: Record<VariableNodeData["type"], string> = {
  continuous: "bg-[var(--node-variable-badge-continuous-bg)] text-[var(--node-variable-badge-continuous-text)]",
  integer: "bg-[var(--node-variable-badge-integer-bg)] text-[var(--node-variable-badge-integer-text)]",
  binary: "bg-[var(--node-variable-badge-binary-bg)] text-[var(--node-variable-badge-binary-text)]",
};

export function VariableNode({ data, selected }: NodeProps<Node<VariableNodeData>>) {
  const t = useTranslations("builder");
  const varData = data as VariableNodeData;

  const boundsLabel =
    varData.lower_bound !== null || varData.upper_bound !== null
      ? `[${varData.lower_bound ?? "-∞"}, ${varData.upper_bound ?? "+∞"}]`
      : null;

  return (
    <div
      className={`
        min-w-36 border bg-card shadow-sm px-3 py-2 transition-colors
        ${selected ? "border-[var(--node-variable-selected)]" : "border-[var(--node-variable)]"}
      `}
    >
      <div className="flex items-center justify-between mb-1">
        <span
          className={`text-[0.625rem] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${TYPE_COLORS[varData.type] || TYPE_COLORS.continuous}`}
        >
          {t(`nodes.${varData.type}`)}
        </span>
      </div>

      <div className="font-mono font-bold text-sm text-foreground truncate">
        {varData.name || t("nodes.unnamed")}
      </div>

      {boundsLabel && (
        <div className="text-xs text-muted-foreground font-mono mt-0.5">{boundsLabel}</div>
      )}

      {/* Source handle — variables connect out to constraints/objective */}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        className="!bg-[var(--node-variable)] !border-[var(--node-variable)]"
      />
    </div>
  );
}
