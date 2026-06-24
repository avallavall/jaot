"use client";

import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
} from "@xyflow/react";
import type { EdgeProps, Edge } from "@xyflow/react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import type { CoefficientEdgeData } from "@/lib/builder/types";

export function CoefficientEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<Edge<CoefficientEdgeData>>) {
  const updateEdgeData = useBuilderStore((s) => s.updateEdgeData);
  const coefficient = data?.coefficient ?? 1;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    if (!isNaN(val)) {
      updateEdgeData(id, { coefficient: val });
    }
  };

  return (
    <>
      <BaseEdge id={id} path={edgePath} className="!stroke-[var(--edge-default)]" />
      <EdgeLabelRenderer>
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: "all",
          }}
          className="nodrag nopan"
        >
          <input
            type="number"
            value={coefficient}
            onChange={handleChange}
            step={0.1}
            className="
              w-12 text-center text-xs font-mono
              bg-background border border-border rounded
              shadow-sm px-1 py-0.5
              focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary
            "
          />
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
