"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { HERO_TRACE } from "./data/heroTrace";

/** Milliseconds spent morphing from one incumbent to the next. */
const MORPH_MS = 1100;
/** Beat between morphs, so each solution is readable before it improves. */
const HOLD_MS = 620;
/** Pause before the "proven optimal" seal lands, standing in for the tree search. */
const PROOF_MS = 900;

type Point = readonly [number, number];

/** Ease-in-out cubic — slow ends, quick middle, so the untangling reads. */
function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Edge k of a tour runs from the k-th stop to the next, closing the loop. Two
 * tours therefore always have the same edge count, which is what lets us morph
 * edge k of one into edge k of the other instead of cross-fading whole shapes.
 */
function edgesOf(tour: readonly number[], points: readonly Point[]): Point[][] {
  return tour.map((stop, k) => [points[stop], points[tour[(k + 1) % tour.length]]]);
}

interface MetricProps {
  label: string;
  value: string;
  className?: string;
}

function Metric({ label, value, className }: MetricProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[0.625rem] uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
      <span className={cn("font-mono text-sm tabular-nums text-foreground", className)}>
        {value}
      </span>
    </div>
  );
}

/**
 * The hero visual: a real optimization run, replayed.
 *
 * Every tour drawn here is an incumbent SCIP found on a 24-stop routing instance
 * and every bound one it proved (see scripts/gen_hero_trace.py) — so the front
 * page is showing the product working, not an illustration of it.
 *
 * The narrative is the point: a good answer arrives almost immediately, and then
 * the solver keeps going to *prove* nothing beats it. That gap between "an
 * answer" and "the answer" is what JAOT sells and what a language model cannot do.
 *
 * Rendering contract:
 * - SSR paints the final, proven state. Crawlers and no-JS visitors get the
 *   finished tour and the real numbers, and the LCP element never waits on JS.
 * - On mount the animation rewinds to the first incumbent and plays forward once.
 * - `prefers-reduced-motion` skips the replay entirely and keeps the proven state.
 */
export function ProvenOptimalHero({ className }: { className?: string }) {
  const t = useTranslations("public.hero.visual");
  const { points, frames, meta } = HERO_TRACE;

  const lastFrame = frames.length - 1;
  // Start settled: this is what the server renders and what reduced-motion keeps.
  const [progress, setProgress] = useState(lastFrame);
  const [proven, setProven] = useState(true);
  const rafRef = useRef<number | undefined>(undefined);
  const timerRef = useRef<number | undefined>(undefined);

  const tourEdges = useMemo(
    () => frames.map((frame) => edgesOf(frame.tour, points as readonly Point[])),
    [frames, points],
  );
  const firstEdges = tourEdges[0];
  /** How much the search improved on its own first feasible answer. */
  const improvement = ((frames[0].cost - meta.optimum) / frames[0].cost) * 100;

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const legMs = MORPH_MS + HOLD_MS;
    const totalMs = lastFrame * legMs;
    let startedAt: number | undefined;

    const step = (now: number) => {
      // Rewind on the first animation frame rather than in the effect body: the
      // clock is the external system driving this component, and rewinding here
      // keeps the server-rendered proven state on screen until playback starts.
      if (startedAt === undefined) {
        startedAt = now;
        setProgress(0);
        setProven(false);
        rafRef.current = requestAnimationFrame(step);
        return;
      }

      const elapsed = now - startedAt;

      if (elapsed >= totalMs) {
        setProgress(lastFrame);
        // The proof is the trailing stretch of the search: the incumbent stops
        // improving well before the tree is exhausted.
        timerRef.current = window.setTimeout(() => setProven(true), PROOF_MS);
        return;
      }

      const leg = Math.floor(elapsed / legMs);
      const withinLeg = Math.min((elapsed - leg * legMs) / MORPH_MS, 1);
      setProgress(leg + ease(withinLeg));
      rafRef.current = requestAnimationFrame(step);
    };

    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
      if (timerRef.current !== undefined) clearTimeout(timerRef.current);
    };
  }, [lastFrame]);

  const from = Math.min(Math.floor(progress), lastFrame);
  const to = Math.min(from + 1, lastFrame);
  const blend = progress - from;

  // Morph edge-by-edge between the two incumbents rather than swapping shapes.
  const edges = tourEdges[from].map((edge, k) => {
    const target = tourEdges[to][k];
    return {
      x1: lerp(edge[0][0], target[0][0], blend),
      y1: lerp(edge[0][1], target[0][1], blend),
      x2: lerp(edge[1][0], target[1][0], blend),
      y2: lerp(edge[1][1], target[1][1], blend),
    };
  });

  const cost = lerp(frames[from].cost, frames[to].cost, blend);
  const dual = lerp(frames[from].dual, frames[to].dual, blend);
  const gap = proven ? 0 : cost > 0 ? ((cost - dual) / cost) * 100 : 0;
  const nodes = proven ? meta.nodes : Math.round(lerp(frames[from].nodes, frames[to].nodes, blend));

  const settled = proven || progress >= lastFrame;

  return (
    <div
      className={cn(
        "overflow-hidden border border-border bg-card shadow-warm-lg",
        className,
      )}
    >
      {/* Window chrome, matching ProductFrame so the hero reads as the product. */}
      <div className="flex items-center gap-2 border-b border-border bg-muted/50 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#E8A088]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#8AA499]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#9B8E88]" />
        <span className="ml-3 truncate font-mono text-xs text-muted-foreground">
          {t("windowLabel", { stops: meta.stops, solver: meta.solver })}
        </span>
      </div>

      <div className="relative bg-background/40">
        <svg
          viewBox="0 0 100 100"
          className="block h-auto w-full"
          role="img"
          aria-label={t("alt", {
            stops: meta.stops,
            optimum: meta.optimum.toFixed(0),
            variables: meta.variables,
          })}
        >
          {/* Faint grid — graph paper, echoing the vintage/print aesthetic. */}
          <defs>
            <pattern id="hero-grid" width="10" height="10" patternUnits="userSpaceOnUse">
              <path
                d="M 10 0 L 0 0 0 10"
                fill="none"
                stroke="currentColor"
                strokeWidth="0.15"
                className="text-border"
              />
            </pattern>
          </defs>
          <rect width="100" height="100" fill="url(#hero-grid)" />

          {/* The starting solution, kept as a ghost. Without it the finished tour
              is just a shape; with it you can see what was improved away — which
              is the whole story, and it survives a screenshot or reduced motion. */}
          {firstEdges.map((edge, k) => (
            <line
              key={`ghost-${k}`}
              x1={edge[0][0]}
              y1={edge[0][1]}
              x2={edge[1][0]}
              y2={edge[1][1]}
              strokeWidth="0.35"
              strokeDasharray="1.4 1.4"
              strokeLinecap="round"
              stroke="currentColor"
              className="text-muted-foreground"
              opacity={settled ? 0.2 : 0}
              style={{ transition: "opacity 700ms ease-out" }}
            />
          ))}

          {edges.map((edge, k) => (
            <line
              key={k}
              x1={edge.x1}
              y1={edge.y1}
              x2={edge.x2}
              y2={edge.y2}
              strokeWidth={settled ? 0.9 : 0.65}
              strokeLinecap="round"
              className={cn(
                "transition-[stroke,stroke-width] duration-700",
                settled ? "text-primary" : "text-accent",
              )}
              stroke="currentColor"
              opacity={settled ? 0.95 : 0.75}
            />
          ))}

          {points.map(([x, y], k) => (
            <circle
              key={k}
              cx={x}
              cy={y}
              r={k === 0 ? 1.6 : 1.05}
              className={k === 0 ? "text-primary" : "text-foreground"}
              fill="currentColor"
              opacity={k === 0 ? 1 : 0.55}
            />
          ))}
        </svg>

        {/* Legend for the ghost: names what the dashed tour was, and states the
            improvement as a figure anyone can check against the metrics row. */}
        <div
          className={cn(
            "pointer-events-none absolute right-3 top-3 border border-border/60 bg-card/85 px-3 py-2 backdrop-blur transition-opacity duration-500 motion-reduce:transition-none",
            settled ? "opacity-100" : "opacity-0",
          )}
        >
          <div className="flex items-center gap-2">
            <svg width="14" height="4" aria-hidden className="shrink-0">
              <line
                x1="0"
                y1="2"
                x2="14"
                y2="2"
                stroke="currentColor"
                strokeWidth="1"
                strokeDasharray="2 2"
                className="text-muted-foreground"
              />
            </svg>
            <span className="font-mono text-[0.625rem] text-muted-foreground">
              {t("legendStart", { cost: frames[0].cost.toFixed(1) })}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <svg width="14" height="4" aria-hidden className="shrink-0">
              <line
                x1="0"
                y1="2"
                x2="14"
                y2="2"
                stroke="currentColor"
                strokeWidth="1.5"
                className="text-primary"
              />
            </svg>
            <span className="font-mono text-[0.625rem] text-foreground">
              {t("legendProven", { cost: meta.optimum.toFixed(1) })}
            </span>
            <span className="font-mono text-[0.625rem] font-medium text-primary">
              −{improvement.toFixed(1)}%
            </span>
          </div>
        </div>

        {/* The seal only appears once optimality is proven — never before. */}
        <div
          className={cn(
            "pointer-events-none absolute bottom-3 left-3 flex items-center gap-2 border border-primary/30 bg-card/90 px-3 py-1.5 backdrop-blur transition-all duration-500 motion-reduce:transition-none",
            proven ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
          )}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-primary">
            {t("proven")}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 border-t border-border px-4 py-3 sm:grid-cols-4">
        <Metric label={t("metrics.cost")} value={cost.toFixed(1)} />
        <Metric
          label={t("metrics.gap")}
          value={`${gap.toFixed(2)}%`}
          className={settled ? "text-primary" : undefined}
        />
        <Metric label={t("metrics.nodes")} value={String(nodes)} />
        <Metric label={t("metrics.variables")} value={String(meta.variables)} />
      </div>
    </div>
  );
}
