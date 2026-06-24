"use client";

import { Handle, Position } from "@xyflow/react";
import type { NodeProps, Node } from "@xyflow/react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useShallow } from "zustand/react/shallow";
import type { ObjectiveNodeData } from "@/lib/builder/types";
import { useTranslations } from "next-intl";

export function ObjectiveNode({ id, data, selected }: NodeProps<Node<ObjectiveNodeData>>) {
  const t = useTranslations("builder");
  const objectiveData = data as ObjectiveNodeData;
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

  const displayFormula = formula || "...";

  return (
    <div
      data-onboarding-target="objective"
      className={`
        min-w-44 border border-t-[3px] bg-[var(--node-objective-bg)] shadow-sm px-3 py-2 transition-colors
        ${selected ? "border-[var(--node-objective-selected)]" : "border-[var(--node-objective)]"}
      `}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[0.625rem] font-bold uppercase tracking-wider text-[var(--node-objective-header)]">
          {t("nodes.objective")}
        </span>
        <span
          className={`text-[0.625rem] px-1.5 py-0.5 rounded font-semibold uppercase ${
            objectiveData.sense === "minimize"
              ? "bg-[var(--node-objective-sense-min-bg)] text-[var(--node-objective-sense-min-text)]"
              : "bg-[var(--node-objective-sense-max-bg)] text-[var(--node-objective-sense-max-text)]"
          }`}
        >
          {t(`nodes.${objectiveData.sense}`)}
        </span>
      </div>

      <div className="font-mono text-sm text-foreground break-all">
        {displayFormula}
      </div>

      {/* Target handle — objective receives from variables */}
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        className="!bg-[var(--node-objective)] !border-[var(--node-objective)]"
      />
    </div>
  );
}
