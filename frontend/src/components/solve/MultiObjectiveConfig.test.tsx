/**
 * MultiObjectiveConfigForm is strictly bi-objective: the backend
 * (app/schemas/optimization.py MultiObjectiveConfig) accepts exactly two
 * objectives. These tests guard that the UI cannot drift back to offering a
 * 3rd/4th objective the server would reject with a 422.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { MultiObjectiveConfig } from "@/lib/types";
import { MultiObjectiveConfigForm } from "./MultiObjectiveConfig";

function renderForm(objectiveCount: 2 = 2) {
  const objectives = Array.from({ length: objectiveCount }, (_, i) => ({
    expression: `x${i}`,
    sense: "minimize" as const,
    weight: 0.5,
    label: `obj-${i}`,
  }));
  const value: MultiObjectiveConfig = { mode: "epsilon", objectives, n_points: 10 };
  return render(
    <NextIntlClientProvider
      locale="en"
      messages={{}}
      onError={() => {}}
      getMessageFallback={({ key }) => key}
    >
      <MultiObjectiveConfigForm value={value} onChange={vi.fn()} />
    </NextIntlClientProvider>,
  );
}

describe("MultiObjectiveConfigForm — strictly bi-objective", () => {
  it("renders exactly two objective sections", () => {
    renderForm();
    expect(screen.getByTestId("objective-expression-0")).toBeInTheDocument();
    expect(screen.getByTestId("objective-expression-1")).toBeInTheDocument();
    expect(screen.queryByTestId("objective-expression-2")).not.toBeInTheDocument();
  });

  it("offers no control to add a third objective", () => {
    renderForm();
    expect(screen.queryByTestId("add-objective-btn")).not.toBeInTheDocument();
  });

  it("offers no control to remove an objective (both are required)", () => {
    renderForm();
    // onRemove is null for every section → the remove button is never rendered.
    expect(screen.queryByLabelText(/removeObjective/i)).not.toBeInTheDocument();
  });
});
