import { describe, it, expect } from "vitest";
import {
  toProgressPoint,
  computeMetrics,
  type SolveProgressEvent,
} from "../live-solve-metrics";

describe("toProgressPoint", () => {
  it("maps a full event to the chart ProgressPoint shape", () => {
    const event: SolveProgressEvent = {
      iteration: 4,
      node: 12,
      objective: 1240,
      primal_bound: 1240,
      dual_bound: 1100,
      gap: 0.1129,
      elapsed_seconds: 2.5,
    };
    expect(toProgressPoint(event, 3)).toEqual({
      iteration: 4,
      objective: 1240,
      gap: 0.1129,
      timestamp: 2500,
    });
  });

  it("falls back to primal_bound when objective is absent", () => {
    const p = toProgressPoint({ primal_bound: 50, gap: 0, elapsed_seconds: 1 }, 0);
    expect(p?.objective).toBe(50);
  });

  it("uses index+1 for iteration and index for timestamp when missing", () => {
    const p = toProgressPoint({ objective: 7 }, 2);
    expect(p).toEqual({ iteration: 3, objective: 7, gap: 0, timestamp: 2 });
  });

  it("returns null when there is no finite objective yet", () => {
    expect(toProgressPoint({ gap: 0.5, elapsed_seconds: 1 }, 0)).toBeNull();
    expect(toProgressPoint({ objective: Number.POSITIVE_INFINITY }, 0)).toBeNull();
    expect(toProgressPoint({ objective: Number.NaN }, 0)).toBeNull();
  });

  it("treats a non-finite gap as 0", () => {
    const p = toProgressPoint({ objective: 1, gap: Number.NaN }, 0);
    expect(p?.gap).toBe(0);
  });
});

describe("computeMetrics", () => {
  it("derives the latest metrics from the accumulated points + last event", () => {
    const points = [
      { iteration: 1, objective: 2000, gap: 0.5, timestamp: 1000 },
      { iteration: 2, objective: 1500, gap: 0.2, timestamp: 3000 },
      { iteration: 3, objective: 1240, gap: 0.05, timestamp: 4200 },
    ];
    const lastEvent: SolveProgressEvent = { node: 87, objective: 1240 };
    expect(computeMetrics(points, lastEvent)).toEqual({
      bestObjective: 1240,
      gap: 0.05,
      nodes: 87,
      incumbents: 3,
      elapsedSeconds: 4.2,
    });
  });

  it("returns empty metrics with no points", () => {
    expect(computeMetrics([], null)).toEqual({
      bestObjective: null,
      gap: null,
      nodes: null,
      incumbents: 0,
      elapsedSeconds: null,
    });
  });

  it("reports null nodes when the last event lacks a node count", () => {
    const points = [{ iteration: 1, objective: 5, gap: 0, timestamp: 0 }];
    expect(computeMetrics(points, { objective: 5 }).nodes).toBeNull();
  });
});
