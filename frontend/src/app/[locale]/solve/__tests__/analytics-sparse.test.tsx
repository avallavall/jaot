import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DistributionPieCard } from "../analytics/page";

// A distribution with one category must read as a sentence, not draw a donut
// of a single colour — the sparse-data rule the author area already follows.
describe("DistributionPieCard sparse data", () => {
  it("renders a sentence instead of a one-colour donut for a single category", () => {
    render(
      <DistributionPieCard
        title="Status"
        data={[{ name: "Completed", value: 4, fill: "#22c55e" }]}
        noDataLabel="No data"
        formatSingle={(name, count) => `All ${count} runs: ${name}.`}
      />,
    );

    expect(screen.getByText("All 4 runs: Completed.")).toBeInTheDocument();
    // No legend rows: the chart body is not rendered.
    expect(screen.queryByText("4")).not.toBeInTheDocument();
  });

  it("still charts a real distribution", () => {
    render(
      <DistributionPieCard
        title="Status"
        data={[
          { name: "Completed", value: 4, fill: "#22c55e" },
          { name: "Failed", value: 2, fill: "#ef4444" },
        ]}
        noDataLabel="No data"
        formatSingle={(name, count) => `All ${count} runs: ${name}.`}
      />,
    );

    // Legend rows accompany the pie.
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.queryByText(/All \d+ runs/)).not.toBeInTheDocument();
  });

  it("keeps the empty state for no data at all", () => {
    render(
      <DistributionPieCard
        title="Status"
        data={[]}
        noDataLabel="No executions found."
        formatSingle={(name, count) => `All ${count} runs: ${name}.`}
      />,
    );

    expect(screen.getByText("No executions found.")).toBeInTheDocument();
  });
});
