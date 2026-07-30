"use client";

import { useCallback, useEffect, useRef, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  useNodesInitialized,
  type NodeTypes,
  type EdgeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  useBuilderStore,
  useTemporalStore,
  pauseTracking,
  resumeTracking,
} from "@/hooks/useBuilderStore";
import { VariableNode } from "./nodes/VariableNode";
import { ConstraintNode } from "./nodes/ConstraintNode";
import { ObjectiveNode } from "./nodes/ObjectiveNode";
import { CoefficientEdge } from "./edges/CoefficientEdge";
import { useTranslations } from "next-intl";

// Module-level constants — NOT inside component (React Flow anti-pattern)
const nodeTypes: NodeTypes = {
  variable: VariableNode as NodeTypes[string],
  constraint: ConstraintNode as NodeTypes[string],
  objective: ObjectiveNode as NodeTypes[string],
};

const edgeTypes: EdgeTypes = {
  coefficient: CoefficientEdge as EdgeTypes[string],
};

export function BuilderCanvas() {
  const t = useTranslations("builder");
  const { screenToFlowPosition, fitView } = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const contextMenuPos = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const lastFittedCount = useRef(0);

  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setSelectedNode,
    addNode,
  } = useBuilderStore();

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string }) => {
      setSelectedNode(node.id);
    },
    [setSelectedNode],
  );

  const handlePaneClick = useCallback(() => {
    setSelectedNode(null);
  }, [setSelectedNode]);

  const handleDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const handleDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/reactflow");
      if (!type || (type !== "variable" && type !== "constraint")) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      addNode(type as "variable" | "constraint", position);
    },
    [screenToFlowPosition, addNode],
  );

  const handleContextMenu = useCallback(
    (event: React.MouseEvent) => {
      contextMenuPos.current = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
    },
    [screenToFlowPosition],
  );

  const handleAddFromContext = useCallback(
    (type: "variable" | "constraint") => {
      addNode(type, contextMenuPos.current);
    },
    [addNode],
  );

  // Global keyboard shortcuts for undo/redo
  const { undo, redo } = useTemporalStore();
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          redo();
        } else {
          undo();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [undo, redo]);

  // Frame a model that arrives after mount.
  //
  // React Flow's `fitView` prop runs once, on mount, against whatever nodes exist
  // then — and the store starts with a single objective node, so it fit to one
  // node and, having no extent to work with, zoomed to `maxZoom`. A 42-node model
  // loading a moment later inherited that 4x zoom: two nodes on screen out of 42,
  // and nothing ever re-framed it. Measured before the fix: scale(4) with 2 of 42
  // visible; the toolbar's own fit button gave scale(0.28) with 42 of 42.
  //
  // A loaded document arrives as one batch, so a jump of more than one node means
  // "a model was just loaded" — while dragging a node in adds exactly one and must
  // NOT move the view the user is working in.
  useEffect(() => {
    const previous = lastFittedCount.current;
    lastFittedCount.current = nodes.length;
    if (!nodesInitialized || nodes.length - previous <= 1) return;
    fitView({ padding: 0.3, maxZoom: 1 });
  }, [nodesInitialized, nodes.length, fitView]);

  return (
    <div className="flex-1" data-onboarding-target="canvas">
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div className="h-full w-full" onContextMenu={handleContextMenu}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={handleNodeClick}
              onPaneClick={handlePaneClick}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onNodeDragStart={pauseTracking}
              onNodeDragStop={resumeTracking}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              defaultEdgeOptions={{ type: "coefficient" }}
              fitView
              // `maxZoom: 1` applies to FRAMING only, not to what the user may zoom
              // to by hand (that is `maxZoom` below). Without it, fitting a canvas
              // holding just the initial objective node has no extent to scale to
              // and blows up to 4x — the state this lens opened in.
              fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
              minZoom={0.1}
              maxZoom={4}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={20} />
              <Controls />
              <MiniMap
                nodeStrokeWidth={3}
                className="!bg-background !border-border"
                style={{ width: 200, height: 150 }}
              />
            </ReactFlow>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem onClick={() => handleAddFromContext("variable")}>
            {t("canvas.addVariable")}
          </ContextMenuItem>
          <ContextMenuItem onClick={() => handleAddFromContext("constraint")}>
            {t("canvas.addConstraint")}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    </div>
  );
}
