"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps, Node } from "@xyflow/react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useShallow } from "zustand/react/shallow";
import type { ConstraintNodeData } from "@/lib/builder/types";
import { useTranslations } from "next-intl";

export function ConstraintNode({ id, data, selected }: NodeProps<Node<ConstraintNodeData>>) {
  const t = useTranslations("builder");
  const constraintData = data as ConstraintNodeData;
  const { nodes, edges } = useBuilderStore(useShallow((s) => ({ nodes: s.nodes, edges: s.edges })));

  // Build formula from incoming edges
  const incomingEdges = edges.filter((e) => e.target === id);
  const formula = incomingEdges
    .map((edge) => {
      const coefficient = edge.data?.coefficient ?? 1;
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const varName =
        sourceNode?.type === "variable"
          ? ((sourceNode.data as { name?: string }).name ?? sourceNode.id)
          : edge.source;
      const coefStr = coefficient === 1 ? "" : coefficient === -1 ? "-" : `${coefficient}`;
      return `${coefStr}${varName}`;
    })
    .join(" + ")
    .replace(/\+ -/g, "- ");

  const displayFormula = formula
    ? `${formula} ${constraintData.operator} ${constraintData.rhs}`
    : `... ${constraintData.operator} ${constraintData.rhs}`;

  return (
    <div
      className={`
        min-w-44 border bg-card shadow-sm px-3 py-2 transition-colors border-l-[3px]
        ${selected ? "border-[var(--node-constraint-selected)]" : "border-[var(--node-constraint)]"}
      `}
    >
      <div className="text-[0.625rem] text-muted-foreground uppercase tracking-wider mb-1">
        {constraintData.name || t("nodes.constraint").toLowerCase()}
      </div>

      <div className="font-mono text-sm text-foreground break-all">
        {displayFormula}
      </div>

      {/* Target handle — constraints receive from variables */}
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        className="!bg-[var(--node-constraint)] !border-[var(--node-constraint)]"
      />
    </div>
  );
}
