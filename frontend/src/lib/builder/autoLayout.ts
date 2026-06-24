
// Dagre-based auto-layout for imported/deserialized models

import dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 80;

/**
 * Apply a left-to-right Dagre layout to a set of nodes and edges.
 * Returns new nodes with updated position values (edges are returned unchanged).
 */
export function applyDagreLayout<N extends Node, E extends Edge>(
  nodes: N[],
  edges: E[]
): { nodes: N[]; edges: E[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: "LR",
    ranksep: 100,
    nodesep: 50,
  });

  // Register all nodes
  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  // Register all edges
  for (const edge of edges) {
    if (edge.source && edge.target) {
      g.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(g);

  // Apply computed positions (Dagre centers nodes on x/y)
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = g.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - NODE_WIDTH / 2,
        y: nodeWithPosition.y - NODE_HEIGHT / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
