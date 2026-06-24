"use client";

import { create } from "zustand";
import { temporal } from "zundo";
import { applyNodeChanges, applyEdgeChanges, addEdge } from "@xyflow/react";
import type { NodeChange, EdgeChange, Connection } from "@xyflow/react";
import type {
  BuilderNode,
  BuilderEdge,
  BuilderNodeData,
  VariableNodeData,
  ConstraintNodeData,
  ObjectiveNodeData,
  CoefficientEdgeData,
} from "@/lib/builder/types";

// Objective node is always present and not deletable.
const OBJECTIVE_NODE_ID = "objective-1";

function createInitialObjectiveNode(): BuilderNode {
  return {
    id: OBJECTIVE_NODE_ID,
    type: "objective",
    position: { x: 400, y: 200 },
    deletable: false,
    data: {
      sense: "minimize",
      formula: "",
    } satisfies ObjectiveNodeData,
  };
}

interface BuilderStore {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
  selectedNodeId: string | null;
  documentId: string | null;
  documentName: string;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  setSelectedNode: (id: string | null) => void;
  updateNodeData: (id: string, data: Partial<BuilderNodeData>) => void;
  addNode: (type: "variable" | "constraint", position: { x: number; y: number }) => void;
  deleteNode: (id: string) => void;
  updateEdgeData: (id: string, data: Partial<CoefficientEdgeData>) => void;
  setDocument: (
    id: string,
    name: string,
    nodes: BuilderNode[],
    edges: BuilderEdge[]
  ) => void;
  reset: () => void;
}

let nodeCounter = 1;
function generateId(prefix: string): string {
  return `${prefix}-${Date.now()}-${nodeCounter++}`;
}

function createVariableData(name: string): VariableNodeData {
  return {
    name,
    type: "continuous",
    lower_bound: 0,
    upper_bound: null,
  };
}

function createConstraintData(name: string): ConstraintNodeData {
  return {
    name,
    operator: "<=",
    rhs: 0,
    formula: "",
  };
}

export const useBuilderStore = create<BuilderStore>()(
  temporal(
    (set, get) => ({
      nodes: [createInitialObjectiveNode()],
      edges: [],
      selectedNodeId: null,
      documentId: null,
      documentName: "Untitled Model",

      onNodesChange: (changes: NodeChange[]) => {
        set((state) => ({
          nodes: applyNodeChanges(changes, state.nodes) as BuilderNode[],
        }));
      },

      onEdgesChange: (changes: EdgeChange[]) => {
        set((state) => ({
          edges: applyEdgeChanges(changes, state.edges) as BuilderEdge[],
        }));
      },

      onConnect: (connection: Connection) => {
        const newEdge: BuilderEdge = {
          ...connection,
          id: generateId("edge"),
          type: "coefficient",
          data: { coefficient: 1 },
        } as BuilderEdge;
        set((state) => ({
          edges: addEdge(newEdge, state.edges) as BuilderEdge[],
        }));
      },

      setSelectedNode: (id: string | null) => {
        // Selection is excluded from undo history (see partialize below).
        useBuilderStore.setState({ selectedNodeId: id });
      },

      updateNodeData: (id: string, data: Partial<BuilderNodeData>) => {
        set((state) => ({
          nodes: state.nodes.map((node) =>
            node.id === id
              ? ({ ...node, data: { ...node.data, ...data } } as BuilderNode)
              : node
          ) as BuilderNode[],
        }));
      },

      addNode: (type: "variable" | "constraint", position: { x: number; y: number }) => {
        const id = generateId(type);
        const existingCount = get().nodes.filter((n) => n.type === type).length;
        const name = type === "variable" ? `x${existingCount + 1}` : `c${existingCount + 1}`;

        const newNode: BuilderNode =
          type === "variable"
            ? {
                id,
                type: "variable",
                position,
                data: createVariableData(name),
              }
            : {
                id,
                type: "constraint",
                position,
                data: createConstraintData(name),
              };

        set((state) => ({
          nodes: [...state.nodes, newNode],
        }));
      },

      deleteNode: (id: string) => {
        const node = get().nodes.find((n) => n.id === id);
        if (!node || node.type === "objective") return; // objective is non-deletable

        set((state) => ({
          nodes: state.nodes.filter((n) => n.id !== id),
          edges: state.edges.filter((e) => e.source !== id && e.target !== id),
        }));
      },

      updateEdgeData: (id: string, data: Partial<CoefficientEdgeData>) => {
        set((state) => ({
          edges: state.edges.map((edge) =>
            edge.id === id
              ? { ...edge, data: { ...edge.data, ...data } as CoefficientEdgeData }
              : edge
          ),
        }));
      },

      setDocument: (
        id: string,
        name: string,
        nodes: BuilderNode[],
        edges: BuilderEdge[]
      ) => {
        set({ documentId: id, documentName: name, nodes, edges });
      },

      reset: () => {
        set({
          nodes: [createInitialObjectiveNode()],
          edges: [],
          selectedNodeId: null,
          documentId: null,
          documentName: "Untitled Model",
        });
      },
    }),
    {
      // Exclude transient state (selection, doc metadata) from undo history.
      partialize: (state) => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { selectedNodeId, documentId, documentName, ...tracked } = state;
        return tracked as Pick<BuilderStore, "nodes" | "edges">;
      },
      limit: 100,
    }
  )
);

export const useTemporalStore = () => useBuilderStore.temporal.getState();

export function pauseTracking() {
  useBuilderStore.temporal.getState().pause();
}

export function resumeTracking() {
  useBuilderStore.temporal.getState().resume();
}
