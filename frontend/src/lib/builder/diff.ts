// Structured diffs between two canvas snapshots, grouped by node type.

export interface FieldChange {
  field: string;
  from: unknown;
  to: unknown;
}

export interface NodeChange {
  type: "added" | "removed" | "modified";
  nodeId: string;
  nodeName: string;
  nodeType: "variable" | "constraint" | "objective";
  fields?: FieldChange[];
}

export interface EdgeChange {
  type: "added" | "removed" | "modified";
  edgeId: string;
  sourceNode: string;
  targetNode: string;
  fields?: FieldChange[];
}

export interface CanvasDiff {
  variables: NodeChange[];
  constraints: NodeChange[];
  objective: NodeChange[];
  edges: EdgeChange[];
  summary: string;
  isEmpty: boolean;
}

interface RawNode {
  id: string;
  type?: string;
  data?: Record<string, unknown>;
}

interface RawEdge {
  id: string;
  source?: string;
  target?: string;
  data?: Record<string, unknown>;
}

function getNodeName(node: RawNode): string {
  if (!node.data) return node.id;
  const d = node.data;
  if (typeof d["name"] === "string" && d["name"]) return d["name"];
  if (typeof d["sense"] === "string") return `Objective (${d["sense"]})`;
  return node.id;
}

function getNodeType(node: RawNode): "variable" | "constraint" | "objective" {
  if (node.type === "variable") return "variable";
  if (node.type === "constraint") return "constraint";
  if (node.type === "objective") return "objective";
  // Inspect data as a fallback when type field is missing.
  if (node.data) {
    if ("lower_bound" in node.data || "upper_bound" in node.data) return "variable";
    if ("operator" in node.data || "rhs" in node.data) return "constraint";
    if ("sense" in node.data) return "objective";
  }
  return "variable"; // defensive default
}

function diffDataFields(prevData: Record<string, unknown>, nextData: Record<string, unknown>): FieldChange[] {
  const changes: FieldChange[] = [];
  const allKeys = new Set([...Object.keys(prevData), ...Object.keys(nextData)]);

  // Auto-computed display fields to skip.
  const skipFields = new Set(["formula", "id"]);

  for (const key of allKeys) {
    if (skipFields.has(key)) continue;
    const prev = prevData[key];
    const next = nextData[key];
    if (JSON.stringify(prev) !== JSON.stringify(next)) {
      changes.push({ field: key, from: prev, to: next });
    }
  }
  return changes;
}

function buildNodeMap(nodes: unknown[]): Map<string, RawNode> {
  const map = new Map<string, RawNode>();
  for (const n of nodes) {
    const node = n as RawNode;
    if (node?.id) map.set(node.id, node);
  }
  return map;
}

function buildEdgeMap(edges: unknown[]): Map<string, RawEdge> {
  const map = new Map<string, RawEdge>();
  for (const e of edges) {
    const edge = e as RawEdge;
    if (edge?.id) map.set(edge.id, edge);
  }
  return map;
}

function buildSummary(
  variables: NodeChange[],
  constraints: NodeChange[],
  objective: NodeChange[],
  edges: EdgeChange[]
): string {
  const parts: string[] = [];

  // Order: adds, removes, mods — matches backend priority.
  const adds: string[] = [];
  const removes: string[] = [];
  const mods: string[] = [];

  for (const c of [...variables, ...constraints, ...objective]) {
    const label = c.nodeName;
    if (c.type === "added") adds.push(`Added ${c.nodeType} ${label}`);
    else if (c.type === "removed") removes.push(`Removed ${c.nodeType} ${label}`);
    else mods.push(`Modified ${c.nodeType} ${label}`);
  }

  for (const e of edges) {
    if (e.type === "added") adds.push(`Added edge ${e.sourceNode}→${e.targetNode}`);
    else if (e.type === "removed") removes.push(`Removed edge ${e.sourceNode}→${e.targetNode}`);
    else mods.push(`Modified edge ${e.sourceNode}→${e.targetNode}`);
  }

  parts.push(...adds, ...removes, ...mods);

  if (parts.length === 0) return "No changes";
  if (parts.length > 3) {
    return `${parts.slice(0, 3).join("; ")}; and ${parts.length - 3} more change(s)`;
  }
  return parts.join("; ");
}

/** prev=null treats next as an initial version. */
export function diffCanvasJson(
  prev: { nodes?: unknown[]; edges?: unknown[] } | null,
  next: { nodes?: unknown[]; edges?: unknown[] }
): CanvasDiff {
  const prevNodes = prev?.nodes ?? [];
  const nextNodes = next?.nodes ?? [];
  const prevEdges = prev?.edges ?? [];
  const nextEdges = next?.edges ?? [];

  const prevNodeMap = buildNodeMap(prevNodes);
  const nextNodeMap = buildNodeMap(nextNodes);
  const prevEdgeMap = buildEdgeMap(prevEdges);
  const nextEdgeMap = buildEdgeMap(nextEdges);

  const variables: NodeChange[] = [];
  const constraints: NodeChange[] = [];
  const objective: NodeChange[] = [];

  if (prev === null) {
    for (const [, node] of nextNodeMap) {
      const nodeType = getNodeType(node);
      const change: NodeChange = {
        type: "added",
        nodeId: node.id,
        nodeName: getNodeName(node),
        nodeType,
      };
      if (nodeType === "variable") variables.push(change);
      else if (nodeType === "constraint") constraints.push(change);
      else objective.push(change);
    }

    const edges: EdgeChange[] = [];
    for (const [, edge] of nextEdgeMap) {
      edges.push({
        type: "added",
        edgeId: edge.id,
        sourceNode: edge.source ?? "",
        targetNode: edge.target ?? "",
      });
    }

    return {
      variables,
      constraints,
      objective,
      edges,
      summary: "Initial version",
      isEmpty: nextNodeMap.size === 0 && nextEdgeMap.size === 0,
    };
  }

  for (const [id, node] of nextNodeMap) {
    if (!prevNodeMap.has(id)) {
      const nodeType = getNodeType(node);
      const change: NodeChange = {
        type: "added",
        nodeId: id,
        nodeName: getNodeName(node),
        nodeType,
      };
      if (nodeType === "variable") variables.push(change);
      else if (nodeType === "constraint") constraints.push(change);
      else objective.push(change);
    }
  }

  for (const [id, node] of prevNodeMap) {
    if (!nextNodeMap.has(id)) {
      const nodeType = getNodeType(node);
      const change: NodeChange = {
        type: "removed",
        nodeId: id,
        nodeName: getNodeName(node),
        nodeType,
      };
      if (nodeType === "variable") variables.push(change);
      else if (nodeType === "constraint") constraints.push(change);
      else objective.push(change);
    }
  }

  for (const [id, nextNode] of nextNodeMap) {
    const prevNode = prevNodeMap.get(id);
    if (!prevNode) continue; // already counted as added above

    const prevData = prevNode.data ?? {};
    const nextData = nextNode.data ?? {};
    const fieldChanges = diffDataFields(prevData, nextData);

    if (fieldChanges.length > 0) {
      const nodeType = getNodeType(nextNode);
      const change: NodeChange = {
        type: "modified",
        nodeId: id,
        nodeName: getNodeName(nextNode),
        nodeType,
        fields: fieldChanges,
      };
      if (nodeType === "variable") variables.push(change);
      else if (nodeType === "constraint") constraints.push(change);
      else objective.push(change);
    }
  }

  const edges: EdgeChange[] = [];

  for (const [id, edge] of nextEdgeMap) {
    if (!prevEdgeMap.has(id)) {
      edges.push({
        type: "added",
        edgeId: id,
        sourceNode: edge.source ?? "",
        targetNode: edge.target ?? "",
      });
    }
  }

  for (const [id, edge] of prevEdgeMap) {
    if (!nextEdgeMap.has(id)) {
      edges.push({
        type: "removed",
        edgeId: id,
        sourceNode: edge.source ?? "",
        targetNode: edge.target ?? "",
      });
    }
  }

  for (const [id, nextEdge] of nextEdgeMap) {
    const prevEdge = prevEdgeMap.get(id);
    if (!prevEdge) continue;

    const prevData = prevEdge.data ?? {};
    const nextData = nextEdge.data ?? {};
    const fieldChanges = diffDataFields(prevData, nextData);

    if (fieldChanges.length > 0) {
      edges.push({
        type: "modified",
        edgeId: id,
        sourceNode: nextEdge.source ?? "",
        targetNode: nextEdge.target ?? "",
        fields: fieldChanges,
      });
    }
  }

  const isEmpty =
    variables.length === 0 && constraints.length === 0 && objective.length === 0 && edges.length === 0;

  const summary = buildSummary(variables, constraints, objective, edges);

  return {
    variables,
    constraints,
    objective,
    edges,
    summary,
    isEmpty,
  };
}
