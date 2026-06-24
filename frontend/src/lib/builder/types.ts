
// Builder Canvas Type Definitions

import type { Node, Edge } from "@xyflow/react";

export interface VariableNodeData {
  name: string;
  type: "continuous" | "integer" | "binary";
  lower_bound: number | null;
  upper_bound: number | null;
  [key: string]: unknown;
}

export interface ConstraintNodeData {
  name: string;
  operator: "<=" | ">=" | "==";
  rhs: number;
  formula: string; // Auto-computed display string
  [key: string]: unknown;
}

export interface ObjectiveNodeData {
  sense: "minimize" | "maximize";
  formula: string; // Auto-computed display string
  [key: string]: unknown;
}

export interface CoefficientEdgeData {
  coefficient: number;
  [key: string]: unknown;
}

export type BuilderNodeData = VariableNodeData | ConstraintNodeData | ObjectiveNodeData;

export type VariableNode = Node<VariableNodeData, "variable">;
export type ConstraintNode = Node<ConstraintNodeData, "constraint">;
export type ObjectiveNode = Node<ObjectiveNodeData, "objective">;

export type BuilderNode = VariableNode | ConstraintNode | ObjectiveNode;
export type BuilderEdge = Edge<CoefficientEdgeData>;

export interface BuilderState {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
  selectedNodeId: string | null;
  documentId: string | null;
  documentName: string;
}

export interface BuilderActions {
  onNodesChange: (changes: import("@xyflow/react").NodeChange[]) => void;
  onEdgesChange: (changes: import("@xyflow/react").EdgeChange[]) => void;
  onConnect: (connection: import("@xyflow/react").Connection) => void;
  setSelectedNode: (id: string | null) => void;
  updateNodeData: (id: string, data: Partial<BuilderNodeData>) => void;
  addNode: (type: "variable" | "constraint", position: { x: number; y: number }) => void;
  deleteNode: (id: string) => void;
  updateEdgeData: (id: string, data: Partial<CoefficientEdgeData>) => void;
  setDocument: (id: string, name: string, nodes: BuilderNode[], edges: BuilderEdge[]) => void;
  reset: () => void;
}
