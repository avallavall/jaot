/**
 * # CONTRACT-TEST: a comparison of two DIFFERENT models says so.
 *
 * The page compares any two executions it is handed. Driving it, a shipping-cost
 * run and a 150x150 assignment run were compared happily: "Objective Delta +238"
 * between 2,610 and 2,848, and "Variables Changed 22665" with all 22,650
 * variables of the larger model listed as added. Every one of those numbers reads
 * as a finding and none of them mean anything.
 *
 * A warning rather than a refusal, because comparing a model against a fork of it
 * is a real thing to want: the variable names still line up, so the diff is
 * exactly what the reader came for, and those are two different models by every
 * id on the row.
 */
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

import type { ModelExecution } from "@/lib/types";

// The stub returns the full key path, so the assertions below name keys rather
// than English — whether every key exists in all five locales is
// `npm run check-i18n`'s job, not this file's.
vi.mock("next-intl", () => ({
  useTranslations: (ns: string) =>
    Object.assign((key: string) => `${ns}.${key}`, {
      rich: (key: string) => `${ns}.${key}`,
    }),
  useNow: () => new Date(0),
  useFormatter: () => ({}),
}));

import { ExecutionComparisonView, comparisonMismatch } from "../ExecutionComparisonView";

function aRun(overrides: Partial<ModelExecution> = {}): ModelExecution {
  return {
    id: "exe_aaaaaaaaaaaa",
    model_project_id: "mp_shipping",
    organization_model_id: null,
    status: "completed",
    objective_value: 2610,
    created_at: "2026-08-19T10:00:00Z",
    execution_time_ms: 120,
    model_name: "Shipping Cost Minimization",
    result_data: {
      status: "optimal",
      objective_value: 2610,
      solve_time_seconds: 0.12,
      warm_start_used: false,
      solution: { route_a: 1, route_b: 0 },
    },
    ...overrides,
  } as ModelExecution;
}

const OTHER = aRun({
  id: "exe_bbbbbbbbbbbb",
  model_project_id: "mp_assignment",
  model_name: "scenario_14_150x150",
  objective_value: 2848,
  result_data: {
    status: "optimal",
    objective_value: 2848,
    solve_time_seconds: 0.34,
    warm_start_used: false,
    solution: { assign_0_0: 1, assign_0_1: 0 },
  },
} as Partial<ModelExecution>);

describe("comparisonMismatch", () => {
  it("reports a mismatch when the two runs name different model projects", () => {
    const m = comparisonMismatch(aRun(), OTHER, 0);
    expect(m).not.toBeNull();
    expect(m!.labelA).toBe("Shipping Cost Minimization");
    expect(m!.labelB).toBe("scenario_14_150x150");
    expect(m!.nothingInCommon).toBe(true);
  });

  it("says nothing when both runs are of the same model", () => {
    expect(comparisonMismatch(aRun(), aRun({ id: "exe_second" }), 2)).toBeNull();
  });

  it("stays quiet when the rows do not say which model they ran", () => {
    /**
     * An uploaded problem carries no project, so two of those cannot be told
     * apart here. Warning on a pair we cannot identify would teach people to
     * ignore the warning.
     */
    const anonymous = aRun({
      model_project_id: null,
      organization_model_id: null,
      source_kind: null,
      source_id: null,
      model_name: null,
    } as Partial<ModelExecution>);
    const other = aRun({
      id: "exe_other",
      model_project_id: null,
      organization_model_id: null,
      source_kind: null,
      source_id: null,
      model_name: null,
    } as Partial<ModelExecution>);

    expect(comparisonMismatch(anonymous, other, 0)).toBeNull();
  });

  it("falls back to provenance when there is no project id", () => {
    const a = aRun({
      model_project_id: null,
      organization_model_id: null,
      source_kind: "template",
      source_id: "tpl_one",
    } as Partial<ModelExecution>);
    const b = aRun({
      id: "exe_b",
      model_project_id: null,
      organization_model_id: null,
      source_kind: "template",
      source_id: "tpl_two",
    } as Partial<ModelExecution>);

    expect(comparisonMismatch(a, b, 0)).not.toBeNull();
  });

  it("separates a fork, where the names still line up, from an unrelated model", () => {
    const fork = comparisonMismatch(aRun(), aRun({ id: "exe_fork", model_project_id: "mp_fork" }), 8);
    expect(fork!.nothingInCommon).toBe(false);
  });
});

describe("ExecutionComparisonView", () => {
  it("shows the notice above the numbers when the models differ", () => {
    const { getByTestId, container } = render(
      <ExecutionComparisonView executionA={aRun()} executionB={OTHER} />,
    );

    const notice = getByTestId("comparison-model-mismatch");
    expect(notice.textContent).toContain("solve.comparison.differentModels");
    // The stronger wording, because nothing lines up in this pair.
    expect(notice.textContent).toContain("solve.comparison.nothingInCommon");
    // And it sits above the summary, not under the table nobody scrolls to.
    const summary = container.querySelector(".bg-card");
    expect(notice.compareDocumentPosition(summary!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows no notice for two runs of the same model", () => {
    const { queryByTestId } = render(
      <ExecutionComparisonView executionA={aRun()} executionB={aRun({ id: "exe_second" })} />,
    );

    expect(queryByTestId("comparison-model-mismatch")).toBeNull();
  });
});
