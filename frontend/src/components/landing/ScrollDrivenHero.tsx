"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { HERO_TRACE } from "./data/heroTrace";

/** Scroll runway, in viewport heights, over which the solve plays out. */
const RUNWAY_VH = 2.6;
/** Fraction of the runway spent proving optimality after the last improvement. */
const PROOF_TAIL = 0.22;

type Point = readonly [number, number];

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

function edgesOf(tour: readonly number[], points: readonly Point[]): Point[][] {
  return tour.map((stop, k) => [points[stop], points[tour[(k + 1) % tour.length]]]);
}

/**
 * The hero: scrolling IS the solve.
 *
 * Rather than a loop that plays at the page regardless of the reader, the run is
 * bound to scroll position — you drive the optimization by moving down. The tour
 * untangles, the cost falls, the gap closes, and the headline gains weight as the
 * answer improves, because Fraunces is a variable font and its wght/opsz axes are
 * mapped to the same progress value.
 *
 * The last stretch of the runway is deliberately quiet: the incumbent stops
 * improving and the solver keeps going, which is when the proof lands. That beat
 * is the product's actual claim, so it gets its own space.
 *
 * Honesty note: this is the solver working (a real SCIP trace — see
 * scripts/gen_hero_trace.py), NOT a screenshot of a JAOT screen. It deliberately
 * carries no window chrome, because the platform has no route map — one was built
 * and withdrawn — and dressing this as product UI would promise a screen that
 * does not exist.
 *
 * Accessibility and robustness:
 * - The server renders the settled, proven state, so crawlers, no-JS visitors and
 *   the LCP never depend on scroll or on JS.
 * - `prefers-reduced-motion` collapses the runway to a single screen and keeps the
 *   proven state — no sticky, no scroll coupling.
 * - Scroll is never hijacked: the section is a normal tall block with a sticky
 *   child, so flicks, wheel, keyboard and scrollbar all behave as the reader expects.
 */
export function ScrollDrivenHero() {
  const t = useTranslations("public.hero");
  const tv = useTranslations("public.hero.visual");
  const { points, frames, meta } = HERO_TRACE;

  const lastFrame = frames.length - 1;
  const trackRef = useRef<HTMLDivElement>(null);
  // Settled by default: this is the SSR output and the reduced-motion state.
  const [progress, setProgress] = useState(1);
  const [coupled, setCoupled] = useState(false);

  const tourEdges = useMemo(
    () => frames.map((f) => edgesOf(f.tour, points as readonly Point[])),
    [frames, points],
  );

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    const read = () => {
      raf = 0;
      const el = trackRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const travel = rect.height - window.innerHeight;
      if (travel <= 0) return;
      setProgress(clamp01(-rect.top / travel));
    };

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(read);
    };

    // Couple on the first animation frame, not in the effect body: the scroll
    // position is the external system driving this, and deferring keeps the
    // server-rendered proven state on screen until the runway actually exists.
    //
    // Do NOT read here: `coupled` is what gives the section its runway height,
    // and React has not committed that yet, so the measurement would come back
    // with travel <= 0, get discarded, and leave the hero showing its finished
    // state until the first scroll — which then snapped it back to the start.
    // The read happens in the effect below, once the height is on the element.
    let armed = requestAnimationFrame(() => {
      armed = 0;
      setCoupled(true);
    });

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (armed) cancelAnimationFrame(armed);
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  // Once the runway height is committed, take the first real measurement. On a
  // fresh load at the top that yields progress 0, so the hero opens unsolved and
  // the reader does the solving.
  useEffect(() => {
    if (!coupled) return;
    const el = trackRef.current;
    if (!el) return;
    const raf = requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      const travel = rect.height - window.innerHeight;
      if (travel > 0) setProgress(clamp01(-rect.top / travel));
    });
    return () => cancelAnimationFrame(raf);
  }, [coupled]);

  // The solve occupies the first stretch; the proof gets the tail.
  const solveProgress = clamp01(progress / (1 - PROOF_TAIL));
  const proven = progress >= 1 - PROOF_TAIL;

  const position = solveProgress * lastFrame;
  const from = Math.min(Math.floor(position), lastFrame);
  const to = Math.min(from + 1, lastFrame);
  const blend = position - from;

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
  const nodes = proven
    ? meta.nodes
    : Math.round(lerp(frames[from].nodes, frames[to].nodes, blend));

  // Fraunces carries wght and opsz. The headline starts light and small-optical —
  // unresolved — and firms up as the answer does. Same number driving both.
  const headlineStyle = {
    fontVariationSettings: `"wght" ${Math.round(lerp(300, 700, solveProgress))}, "opsz" ${Math.round(
      lerp(14, 144, solveProgress),
    )}`,
  };

  const improvement = ((frames[0].cost - meta.optimum) / frames[0].cost) * 100;
  const firstEdges = tourEdges[0];

  return (
    <section
      ref={trackRef}
      className="relative"
      style={coupled ? { height: `${RUNWAY_VH * 100}vh` } : undefined}
    >
      <div
        className={cn(
          "top-0 flex flex-col justify-center overflow-hidden border-b border-border",
          coupled ? "sticky h-screen" : "relative",
        )}
      >
        <div className="hero-glow pointer-events-none absolute inset-0" aria-hidden />
        <div
          className="bg-grain pointer-events-none absolute inset-0 opacity-[0.05] mix-blend-multiply dark:opacity-[0.08] dark:mix-blend-screen"
          aria-hidden
        />

        <div className="relative mx-auto grid w-full max-w-6xl items-center gap-10 px-6 py-16 lg:grid-cols-[1.05fr_1fr] lg:gap-12">
          <div className="text-center lg:text-left">
            <Badge
              variant="outline"
              className="mb-6 gap-2 bg-background/60 px-4 py-1 text-sm font-normal backdrop-blur"
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
              </span>
              {t("badge")}
            </Badge>

            <h1
              className="mb-6 font-serif text-4xl leading-[1.05] text-balance text-foreground md:text-5xl xl:text-6xl motion-reduce:![font-variation-settings:normal]"
              style={headlineStyle}
            >
              <span className="block break-words">{t("titleLine1")}</span>
              <span className="block break-words">{t("titleLine2")}</span>
              <span className="block break-words text-primary">{t("titleLine3")}</span>
            </h1>

            <p className="mx-auto mb-8 max-w-xl text-lg text-muted-foreground lg:mx-0">
              {t("subtitle")}
            </p>

            <div className="flex flex-col justify-center gap-3 sm:flex-row lg:justify-start">
              <Link href="/signup">
                <Button size="lg" className="w-full gap-2 px-8 shadow-warm-sm sm:w-auto">
                  {t("getStartedFree")}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
              <Link href="/marketplace">
                <Button size="lg" variant="outline" className="w-full gap-2 px-8 sm:w-auto">
                  {t("browseTemplates")}
                </Button>
              </Link>
            </div>
          </div>

          {/* No window chrome: this is the solver running, not a JAOT screen. */}
          <div className="relative">
            <svg
              viewBox="0 0 100 100"
              className="block h-auto w-full"
              role="img"
              aria-label={tv("alt", {
                stops: meta.stops,
                optimum: meta.optimum.toFixed(0),
                variables: meta.variables,
              })}
            >
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

              {/* Where it started, so the improvement reads even standing still. */}
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
                  opacity={0.2 * solveProgress}
                />
              ))}

              {edges.map((edge, k) => (
                <line
                  key={k}
                  x1={edge.x1}
                  y1={edge.y1}
                  x2={edge.x2}
                  y2={edge.y2}
                  strokeWidth={lerp(0.6, 0.95, solveProgress)}
                  strokeLinecap="round"
                  stroke="currentColor"
                  className={proven ? "text-primary" : "text-accent"}
                  opacity={0.75 + 0.2 * solveProgress}
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

            <div
              className={cn(
                "pointer-events-none absolute right-0 top-0 border border-border/60 bg-card/85 px-3 py-2 backdrop-blur transition-opacity duration-500",
                proven ? "opacity-100" : "opacity-0",
              )}
            >
              <p className="font-mono text-[0.625rem] text-muted-foreground">
                {tv("legendStart", { cost: frames[0].cost.toFixed(1) })}
              </p>
              <p className="mt-1 font-mono text-[0.625rem] text-foreground">
                {tv("legendProven", { cost: meta.optimum.toFixed(1) })}{" "}
                <span className="font-medium text-primary">−{improvement.toFixed(1)}%</span>
              </p>
            </div>
          </div>
        </div>

        {/* Live readout, full width: the numbers are the drama. */}
        <div className="relative mx-auto grid w-full max-w-6xl grid-cols-2 gap-4 px-6 pb-4 sm:grid-cols-4">
          <Readout label={tv("metrics.cost")} value={cost.toFixed(1)} />
          <Readout
            label={tv("metrics.gap")}
            value={`${gap.toFixed(2)}%`}
            highlight={proven}
            suffix={proven ? tv("proven") : undefined}
          />
          <Readout label={tv("metrics.nodes")} value={String(nodes)} />
          <Readout label={tv("metrics.variables")} value={String(meta.variables)} />
        </div>
      </div>
    </section>
  );
}

interface ReadoutProps {
  label: string;
  value: string;
  highlight?: boolean;
  suffix?: string;
}

function Readout({ label, value, highlight, suffix }: ReadoutProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[0.625rem] uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-lg tabular-nums transition-colors duration-500",
          highlight ? "text-primary" : "text-foreground",
        )}
      >
        {value}
      </span>
      {suffix ? (
        <span className="font-mono text-[0.625rem] uppercase tracking-wider text-primary">
          {suffix}
        </span>
      ) : null}
    </div>
  );
}
