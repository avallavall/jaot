"use client";

import { useMemo } from "react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useShallow } from "zustand/react/shallow";
import type { VariableNodeData } from "@/lib/builder/types";

export type ValidationSeverity = "error" | "warning";

export interface ValidationIssue {
  /** Unique key for i18n lookup: builder.health.<key> */
  key: string;
  severity: ValidationSeverity;
  /** Optional interpolation params for i18n */
  params?: Record<string, string | number>;
}

export type HealthStatus = "valid" | "warning" | "error";

export interface ModelValidation {
  status: HealthStatus;
  issues: readonly ValidationIssue[];
  errorCount: number;
  warningCount: number;
}

// Pure validation logic — no hooks, testable in isolation.
export function validateModel(
  nodes: readonly { id: string; type?: string; data: Record<string, unknown> }[],
  edges: readonly { id: string; source: string; target: string; data?: Record<string, unknown> }[]
): ModelValidation {
  const issues: ValidationIssue[] = [];

  const variableNodes = nodes.filter((n) => n.type === "variable");
  const constraintNodes = nodes.filter((n) => n.type === "constraint");
  const objectiveNode = nodes.find((n) => n.type === "objective");

  if (!objectiveNode) {
    issues.push({ key: "noObjective", severity: "error" });
  }

  if (variableNodes.length === 0) {
    issues.push({ key: "noVariables", severity: "error" });
  }

  for (const node of variableNodes) {
    const data = node.data as VariableNodeData;
    if (
      data.lower_bound !== null &&
      data.lower_bound !== undefined &&
      data.upper_bound !== null &&
      data.upper_bound !== undefined &&
      data.lower_bound > data.upper_bound
    ) {
      issues.push({
        key: "invalidBounds",
        severity: "error",
        params: { name: data.name || node.id },
      });
    }
  }

  if (constraintNodes.length === 0) {
    issues.push({ key: "noConstraints", severity: "warning" });
  }

  // An edge whose source is not a variable node references something undeclared.
  const variableIds = new Set(variableNodes.map((n) => n.id));

  if (objectiveNode) {
    const objEdges = edges.filter((e) => e.target === objectiveNode.id);

    if (objEdges.length === 0 && variableNodes.length > 0) {
      issues.push({ key: "objectiveNoConnections", severity: "warning" });
    }

    for (const edge of objEdges) {
      if (!variableIds.has(edge.source)) {
        issues.push({
          key: "undeclaredInObjective",
          severity: "error",
          params: { source: edge.source },
        });
      }
    }
  }

  for (const constraint of constraintNodes) {
    const incomingEdges = edges.filter((e) => e.target === constraint.id);

    if (incomingEdges.length === 0) {
      const cData = constraint.data as { name?: string };
      issues.push({
        key: "constraintNoConnections",
        severity: "warning",
        params: { name: cData.name || constraint.id },
      });
    }

    for (const edge of incomingEdges) {
      if (!variableIds.has(edge.source)) {
        const cData = constraint.data as { name?: string };
        issues.push({
          key: "undeclaredInConstraint",
          severity: "error",
          params: {
            source: edge.source,
            constraint: cData.name || constraint.id,
          },
        });
      }
    }
  }

  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.filter((i) => i.severity === "warning").length;

  const status: HealthStatus =
    errorCount > 0 ? "error" : warningCount > 0 ? "warning" : "valid";

  return { status, issues, errorCount, warningCount };
}

export function useModelValidation(): ModelValidation {
  const { nodes, edges } = useBuilderStore(
    useShallow((s) => ({ nodes: s.nodes, edges: s.edges }))
  );

  return useMemo(() => validateModel(nodes, edges), [nodes, edges]);
}
