/**
 * The owner's complaint about the solve analytics screen was that with little
 * data it looked ridiculous: a donut of one colour, one full-width bar, and the
 * same number repeated four times. These tests pin the opposite behaviour for
 * the author panel — with thin data it says what it knows in words, and it only
 * draws once there is genuinely something to draw.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const {
  getAuthorAnalyticsSummary,
  getAuthorAnalyticsFunnel,
  getAuthorAnalyticsGeo,
  getAuthorAnalyticsModels,
  getAuthorAnalyticsTimeSeries,
} = vi.hoisted(() => ({
  getAuthorAnalyticsSummary: vi.fn(),
  getAuthorAnalyticsFunnel: vi.fn(),
  getAuthorAnalyticsGeo: vi.fn(),
  getAuthorAnalyticsModels: vi.fn(),
  getAuthorAnalyticsTimeSeries: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getAuthorAnalyticsSummary,
    getAuthorAnalyticsFunnel,
    getAuthorAnalyticsGeo,
    getAuthorAnalyticsModels,
    getAuthorAnalyticsTimeSeries,
  },
}));

import { AuthorAnalyticsPanel, fillMissingDays } from "../AuthorAnalyticsPanel";

describe("fillMissingDays", () => {
  const day = (date: string, views: number) => ({
    date,
    views,
    impressions: 0,
    activations: 0,
  });

  it("pads the quiet days so three scattered days are not three full-width bars", () => {
    const filled = fillMissingDays(
      [day("2026-07-29", 9), day("2026-07-31", 2)],
      "7d",
      new Date("2026-07-31T12:00:00Z"),
    );

    expect(filled).toHaveLength(7);
    expect(filled[0].date).toBe("2026-07-25");
    expect(filled.at(-1)).toMatchObject({ date: "2026-07-31", views: 2 });
    // The gap on the 30th is a real zero, not a missing column.
    expect(filled.find((d) => d.date === "2026-07-30")).toMatchObject({ views: 0 });
  });

  it("keeps the recorded values where they exist", () => {
    const filled = fillMissingDays([day("2026-07-31", 9)], "7d", new Date("2026-07-31T12:00:00Z"));
    expect(filled.filter((d) => d.views > 0)).toHaveLength(1);
  });

  it("starts an all-time range at the first recorded day", () => {
    const filled = fillMissingDays(
      [day("2026-07-28", 4)],
      "all",
      new Date("2026-07-31T12:00:00Z"),
    );
    expect(filled.map((d) => d.date)).toEqual([
      "2026-07-28",
      "2026-07-29",
      "2026-07-30",
      "2026-07-31",
    ]);
  });

  it("returns nothing for an all-time range with no data at all", () => {
    expect(fillMissingDays([], "all", new Date("2026-07-31T12:00:00Z"))).toEqual([]);
  });
});

const summary = {
  total_views: 68,
  total_impressions: 2000,
  total_activations: 1,
  conversion_rate: 1.5,
  period: "30d",
};

function setup({
  funnel = { impressions: 2000, views: 68, activations: 1 },
  geo = { data: [{ country: "ES", count: 68 }] },
  models = [] as unknown[],
  series = { data: [{ date: "2026-07-31", views: 68, impressions: 2000, activations: 1 }], period: "30d" },
} = {}) {
  getAuthorAnalyticsSummary.mockResolvedValue(summary);
  getAuthorAnalyticsFunnel.mockResolvedValue(funnel);
  getAuthorAnalyticsGeo.mockResolvedValue(geo);
  getAuthorAnalyticsModels.mockResolvedValue(models);
  getAuthorAnalyticsTimeSeries.mockResolvedValue(series);
  return render(<AuthorAnalyticsPanel locale="en" />);
}

describe("AuthorAnalyticsPanel with thin data", () => {
  beforeEach(() => vi.clearAllMocks());

  it("states a single country in words instead of drawing a distribution", async () => {
    setup({ geo: { data: [{ country: "ES", count: 68 }] } });

    expect(await screen.findByText(/author\.analytics\.geoSingle/)).toBeInTheDocument();
    // The sentence replaces the chart: no per-country bar row is rendered.
    // (The mocked translator returns keys, so the interpolated figures live in
    // the message catalogue, not here.)
    expect(screen.queryByText("Spain")).not.toBeInTheDocument();
  });

  it("says a trend needs two days when only one has activity", async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText(/author\.analytics\.trendEmpty/)).toBeInTheDocument();
    });
  });

  it("does not draw a funnel nobody has entered", async () => {
    setup({ funnel: { impressions: 0, views: 0, activations: 0 } });
    await waitFor(() => {
      expect(screen.getByText("author.analytics.funnelEmpty")).toBeInTheDocument();
    });
    expect(screen.queryByText("author.analytics.funnelImpressions")).not.toBeInTheDocument();
  });

  it("says so when no model has been seen", async () => {
    setup({ models: [] });
    await waitFor(() => {
      expect(screen.getByText("author.analytics.perModelEmpty")).toBeInTheDocument();
    });
  });

  it("distinguishes 'no visits' from 'visits whose country we don't know'", async () => {
    // The geo query drops views with a null country, so an empty geo response
    // with views on the counter means unknown origin — not an empty period.
    setup({ geo: { data: [] } });

    await waitFor(() => {
      expect(screen.getByText(/author\.analytics\.geoUnknown/)).toBeInTheDocument();
    });
    expect(screen.queryByText("author.analytics.geoEmpty")).not.toBeInTheDocument();
  });

  it("reports a failure as a failure, not as an empty period", async () => {
    getAuthorAnalyticsSummary.mockRejectedValue(new Error("500"));
    getAuthorAnalyticsFunnel.mockResolvedValue({ impressions: 0, views: 0, activations: 0 });
    getAuthorAnalyticsGeo.mockResolvedValue({ data: [] });
    getAuthorAnalyticsModels.mockResolvedValue([]);
    getAuthorAnalyticsTimeSeries.mockResolvedValue({ data: [], period: "30d" });
    render(<AuthorAnalyticsPanel locale="en" />);

    expect(await screen.findByText("author.analytics.loadFailed")).toBeInTheDocument();
    // None of the "nothing happened yet" copy may appear on an outage.
    expect(screen.queryByText("author.analytics.funnelEmpty")).not.toBeInTheDocument();
    expect(screen.queryByText("author.analytics.geoEmpty")).not.toBeInTheDocument();
    expect(screen.queryByText("author.analytics.perModelEmpty")).not.toBeInTheDocument();
  });

  it("does not draw a trend off a day the chart never shows", async () => {
    // The API window is a timestamp, so 7d can return 8 dated buckets; the chart
    // draws exactly 7. Activity only on the dropped day plus today used to pass
    // the two-active-days gate and then render a single column.
    const today = new Date();
    const iso = (offset: number) => {
      const d = new Date(today);
      d.setUTCDate(d.getUTCDate() - offset);
      return d.toISOString().slice(0, 10);
    };
    setup({
      series: {
        data: [
          { date: iso(7), views: 5, impressions: 0, activations: 0 },
          { date: iso(0), views: 3, impressions: 0, activations: 0 },
        ],
        period: "7d",
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "author.analytics.period7d" }));

    expect(await screen.findByText(/author\.analytics\.trendEmpty/)).toBeInTheDocument();
  });

  it("reports a genuinely empty period as empty", async () => {
    getAuthorAnalyticsSummary.mockResolvedValue({ ...summary, total_views: 0 });
    getAuthorAnalyticsFunnel.mockResolvedValue({ impressions: 0, views: 0, activations: 0 });
    getAuthorAnalyticsGeo.mockResolvedValue({ data: [] });
    getAuthorAnalyticsModels.mockResolvedValue([]);
    getAuthorAnalyticsTimeSeries.mockResolvedValue({ data: [], period: "30d" });
    render(<AuthorAnalyticsPanel locale="en" />);

    await waitFor(() => {
      expect(screen.getByText("author.analytics.geoEmpty")).toBeInTheDocument();
    });
  });
});

describe("AuthorAnalyticsPanel once there is something to plot", () => {
  beforeEach(() => vi.clearAllMocks());

  it("draws the country breakdown with two or more countries", async () => {
    setup({
      geo: {
        data: [
          { country: "ES", count: 40 },
          { country: "DE", count: 28 },
        ],
      },
    });

    await waitFor(() => {
      expect(screen.queryByText(/author\.analytics\.geoSingle/)).not.toBeInTheDocument();
    });
    expect(screen.getByText("Spain")).toBeInTheDocument();
    expect(screen.getByText("Germany")).toBeInTheDocument();
    // 40 + 28 = 68 = every recorded view, so no coverage caveat is needed.
    expect(screen.queryByText(/author\.analytics\.geoCoverage/)).not.toBeInTheDocument();
  });

  it("admits when the bars only cover part of the visits", async () => {
    setup({
      geo: {
        data: [
          { country: "ES", count: 20 },
          { country: "DE", count: 10 },
        ],
      },
    });

    // summary says 68 views; the countries only account for 30 of them.
    expect(await screen.findByText(/author\.analytics\.geoCoverage/)).toBeInTheDocument();
  });

  it("draws the daily trend with two active days", async () => {
    setup({
      series: {
        data: [
          { date: "2026-07-30", views: 20, impressions: 100, activations: 0 },
          { date: "2026-07-31", views: 48, impressions: 200, activations: 1 },
        ],
        period: "30d",
      },
    });

    await waitFor(() => {
      expect(screen.queryByText(/author\.analytics\.trendEmpty/)).not.toBeInTheDocument();
    });
  });

  it("lists per-model performance when models have been seen", async () => {
    setup({
      models: [
        { model_id: "mp_1", model_name: "Routing", views: 40, activations: 1, conversion_rate: 2.5 },
      ],
    });

    await waitFor(() => {
      expect(screen.getByText("Routing")).toBeInTheDocument();
    });
    expect(screen.queryByText("author.analytics.perModelEmpty")).not.toBeInTheDocument();
  });
});
