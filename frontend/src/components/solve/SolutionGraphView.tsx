"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SolutionGraph } from "@/lib/types";

interface SolutionGraphViewProps {
  executionId: string;
}

/** Layout constants — the drawing is deterministic, so these are the whole geometry. */
const COLUMN_WIDTH = 190;
const ROW_HEIGHT = 44;
const NODE_RX = 30;
const NODE_RY = 13;
const MARGIN_X = 44;
const MARGIN_Y = 34;

/**
 * Distinct hues for the groups (vehicles / resources) that own the edges. Kept as
 * explicit CSS colours rather than theme tokens because a categorical scale needs
 * to stay distinguishable from its neighbours, which a semantic token cannot
 * promise. They read on both light and dark backgrounds.
 */
const GROUP_COLORS = [
  "#2563eb",
  "#16a34a",
  "#ea580c",
  "#9333ea",
  "#0891b2",
  "#dc2626",
  "#ca8a04",
  "#4f46e5",
] as const;
const UNGROUPED_COLOR = "var(--muted-foreground)";

interface Placed {
  id: string;
  x: number;
  y: number;
}

/**
 * The graph a solution describes — routing arcs, assignments, flows — drawn from
 * the active entries of any variable family indexed by two or more labels.
 *
 * **Nodes are placed by LAYER, never by geography.** Optimization models carry
 * distances, not coordinates, so a map with real positions would be fabricated.
 * The horizontal axis is the node's position in the flow (a fact derived from the
 * edges); the vertical axis is only separation so the labels do not overlap.
 *
 * Renders nothing at all when the backend reports no graph — an empty frame would
 * imply the model failed at something it was never asked to do.
 */
export function SolutionGraphView({ executionId }: SolutionGraphViewProps) {
  const t = useTranslations("solve.execution.solutionGraph");
  const [graph, setGraph] = useState<SolutionGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeGroup, setActiveGroup] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getExecutionSolutionGraph(executionId)
      .then((res) => {
        if (!cancelled) setGraph(res);
      })
      .catch(() => {
        // A graph is a bonus view; a failure here must never take the page with it.
        if (!cancelled) setGraph(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [executionId]);

  const placement = useMemo(() => place(graph), [graph]);

  if (loading || !graph?.computed || !placement) return null;

  const { positions, width, height, columns } = placement;
  const colorOf = (group: string | null | undefined): string =>
    group == null
      ? UNGROUPED_COLOR
      : GROUP_COLORS[graph.groups.indexOf(group) % GROUP_COLORS.length];

  const dimmed = (group: string | null | undefined): boolean =>
    activeGroup !== null && group !== activeGroup;

  return (
    <div className="mb-6 space-y-3" data-testid="solution-graph">
      {/* The heading lives in here, not in the page: this component renders
          nothing at all for a model with no graph, and a heading left behind
          would announce a section that never arrives. */}
      <h2 className="text-lg font-semibold text-foreground">{t("title")}</h2>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-sm text-muted-foreground">
          {graph.is_network
            ? t("summaryNetwork", { active: graph.active_count, total: graph.candidate_count })
            : t("summaryAssignment", { active: graph.active_count, total: graph.candidate_count })}
        </p>
        {graph.truncated && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            {t("truncated", { shown: graph.edges.length, total: graph.active_count })}
          </p>
        )}
      </div>

      {graph.groups.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="solution-graph-legend">
          {graph.groups.map((group) => (
            <button
              key={group}
              type="button"
              onClick={() => setActiveGroup(activeGroup === group ? null : group)}
              aria-pressed={activeGroup === group}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors",
                activeGroup === group ? "border-foreground/40 bg-muted" : "border-border"
              )}
            >
              <span
                aria-hidden="true"
                className="size-2 rounded-full"
                style={{ background: colorOf(group) }}
              />
              {group}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border bg-card p-2">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={t("ariaLabel", { nodes: graph.nodes.length, edges: graph.edges.length })}
          className="max-w-none"
        >
          <defs>
            {/* One marker per colour: SVG markers cannot inherit the stroke of
                the path that uses them, so an arrowhead would otherwise always
                be black and contradict its own edge. */}
            {GROUP_COLORS.map((color, i) => (
              <marker
                key={i}
                id={`sg-arrow-${i}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="5"
                markerHeight="5"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
              </marker>
            ))}
            <marker
              id="sg-arrow-plain"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={UNGROUPED_COLOR} />
            </marker>
          </defs>

          {columns.map((label, index) => (
            <text
              key={index}
              x={MARGIN_X + index * COLUMN_WIDTH}
              y={16}
              textAnchor="middle"
              className="fill-muted-foreground text-[10px] uppercase tracking-wide"
            >
              {label}
            </text>
          ))}

          {graph.edges.map((edge) => {
            const from = positions.get(edge.source);
            const to = positions.get(edge.target);
            if (!from || !to) return null;
            const groupIndex = edge.group == null ? -1 : graph.groups.indexOf(edge.group);
            const marker =
              groupIndex < 0
                ? "url(#sg-arrow-plain)"
                : `url(#sg-arrow-${groupIndex % GROUP_COLORS.length})`;
            return (
              <path
                key={edge.variable}
                d={edgePath(from, to)}
                fill="none"
                stroke={colorOf(edge.group)}
                strokeWidth={1.6}
                markerEnd={marker}
                opacity={dimmed(edge.group) ? 0.12 : 0.85}
              >
                <title>
                  {edge.variable} = {edge.value}
                </title>
              </path>
            );
          })}

          {[...positions.entries()].map(([id, pos]) => (
            <g key={id}>
              <ellipse
                cx={pos.x}
                cy={pos.y}
                rx={NODE_RX}
                ry={NODE_RY}
                className="fill-background stroke-border"
                strokeWidth={1}
              />
              <text
                x={pos.x}
                y={pos.y + 3.5}
                textAnchor="middle"
                className="fill-foreground font-mono text-[10px]"
              >
                {id}
              </text>
            </g>
          ))}
        </svg>
      </div>

      {/* Said out loud, not buried in a tooltip: the axis is flow order. Anyone
          who reads this as a map of where things ARE would be misled. */}
      <p className="text-xs text-muted-foreground">{t("layoutNote")}</p>
    </div>
  );
}

/**
 * A gentle S-curve between two nodes. A straight line between adjacent columns
 * would be fine, but edges that skip a column would then run straight THROUGH the
 * nodes in between; the curve keeps them readable without implying anything about
 * distance.
 */
function edgePath(from: Placed, to: Placed): string {
  const dx = to.x - from.x;
  const startX = from.x + NODE_RX;
  const endX = to.x - NODE_RX;
  const control = Math.max(24, Math.abs(dx) / 2);
  return `M ${startX} ${from.y} C ${startX + control} ${from.y}, ${endX - control} ${to.y}, ${endX} ${to.y}`;
}

interface Placement {
  positions: Map<string, Placed>;
  width: number;
  height: number;
  columns: string[];
}

/**
 * Turn layers into coordinates: one column per layer, nodes stacked inside it.
 *
 * Column order is the layer number, so the drawing reads left-to-right along the
 * flow. Within a column the order is alphabetical — arbitrary but stable, which
 * matters more than clever crossing-minimisation for the sizes we draw.
 */
function place(graph: SolutionGraph | null): Placement | null {
  if (!graph?.computed || graph.edges.length === 0) return null;

  const byLayer = new Map<number, string[]>();
  for (const node of graph.nodes) {
    const layer = graph.layers[node] ?? 0;
    const bucket = byLayer.get(layer);
    if (bucket) bucket.push(node);
    else byLayer.set(layer, [node]);
  }
  if (byLayer.size === 0) return null;

  const layerKeys = [...byLayer.keys()].sort((a, b) => a - b);
  const positions = new Map<string, Placed>();
  let tallest = 0;

  layerKeys.forEach((layer, column) => {
    const nodes = (byLayer.get(layer) ?? []).slice().sort();
    tallest = Math.max(tallest, nodes.length);
    nodes.forEach((node, row) => {
      positions.set(node, {
        id: node,
        x: MARGIN_X + column * COLUMN_WIDTH,
        y: MARGIN_Y + row * ROW_HEIGHT,
      });
    });
  });

  return {
    positions,
    width: MARGIN_X * 2 + Math.max(0, layerKeys.length - 1) * COLUMN_WIDTH,
    height: MARGIN_Y + tallest * ROW_HEIGHT,
    columns: columnLabels(graph, layerKeys),
  };
}

/**
 * Label each column with the variable family whose edges LEAVE it.
 *
 * A bare "1 2 3 4" says nothing the picture does not already show, while the
 * model does know what each hop is — in the TFM formulation the columns become
 * xsc / xcd / xde, i.e. start->load, load->unload, unload->end. This is read off
 * the edges, so it is a fact rather than a caption we invented; the final column
 * has no outgoing edges and stays blank.
 */
function columnLabels(graph: SolutionGraph, layerKeys: number[]): string[] {
  const perLayer = new Map<number, Map<string, number>>();
  for (const edge of graph.edges) {
    const layer = graph.layers[edge.source] ?? 0;
    const counts = perLayer.get(layer) ?? new Map<string, number>();
    counts.set(edge.family, (counts.get(edge.family) ?? 0) + 1);
    perLayer.set(layer, counts);
  }
  return layerKeys.map((layer) => {
    const counts = perLayer.get(layer);
    if (!counts || counts.size === 0) return "";
    // Ties resolve alphabetically so the label cannot flicker between renders.
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0];
  });
}
