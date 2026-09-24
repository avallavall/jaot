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

// Found driving the studio on 2026-09-24: SCIP proved 485 optimal and the panel
// kept its last live figures, 450 at a 7.78% gap, under "Solved".
describe("computeMetrics once the run is over", () => {
  const live = [
    { iteration: 1, objective: 440, gap: 0.2, timestamp: 400 },
    { iteration: 2, objective: 450, gap: 0.0778, timestamp: 900 },
  ];

  it("takes the objective, gap, nodes and time from the result", () => {
    const m = computeMetrics(live, { node: 1 }, {
      objective_value: 485,
      gap: 0,
      nodes: 12,
      solve_time_seconds: 2.4,
    });
    expect(m).toMatchObject({ bestObjective: 485, gap: 0, nodes: 12, elapsedSeconds: 2.4 });
  });

  it("keeps the live figures for a field the result leaves out", () => {
    const m = computeMetrics(live, { node: 7 }, { objective_value: 485 });
    expect(m).toMatchObject({ bestObjective: 485, gap: 0.0778, nodes: 7 });
  });

  it("counts an incumbent only when the best objective changed", () => {
    // JAOS also sends a point when only the bound moved.
    const points = [
      { iteration: 1, objective: 450, gap: 0.2, timestamp: 100 },
      { iteration: 2, objective: 450, gap: 0.15, timestamp: 400 },
      { iteration: 3, objective: 450, gap: 0.14, timestamp: 700 },
      { iteration: 4, objective: 470, gap: 0.1, timestamp: 900 },
    ];
    expect(computeMetrics(points, null).incumbents).toBe(2);
  });

  it("uses the page clock while the run is live", () => {
    expect(computeMetrics(live, null, null, 30.8).elapsedSeconds).toBe(30.8);
  });
});
