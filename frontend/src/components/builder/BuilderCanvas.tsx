"use client";

import { useCallback, useEffect, useRef, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
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
  const { screenToFlowPosition } = useReactFlow();
  const contextMenuPos = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

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
              fitViewOptions={{ padding: 0.3 }}
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
