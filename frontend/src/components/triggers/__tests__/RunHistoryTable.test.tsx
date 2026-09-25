/**
 * The run history, as the QA pass saw it (2026-09-25).
 *
 * - "Rerun" was offered on a run whose input was refused, and each click added
 *   another refused run.
 * - A webhook that had failed three times, with its last retry still scheduled,
 *   showed "—" in the Webhook column.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import React from "react";
import type { TriggerRun } from "@/lib/types";
import { canRerun, webhookState } from "../run-history";

const { list } = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { triggers: { runs: { list, rerun: vi.fn() } } },
  ApiError: class ApiError extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { RunHistoryTable } from "../RunHistoryTable";

function run(overrides: Partial<TriggerRun>): TriggerRun {
  return {
    id: "trun_x",
    trigger_id: "trg_1",
    organization_id: "org_1",
    source: "manual",
    status: "completed",
    webhook_attempts: 0,
    created_at: "2026-09-25T00:00:00Z",
    ...overrides,
  };
}

describe("webhookState", () => {
  it("reads every combination the delivery task writes", () => {
    expect(webhookState({ webhook_delivered: true, webhook_attempts: 1 }).kind).toBe("delivered");
    expect(webhookState({ webhook_delivered: false, webhook_attempts: 4 })).toEqual({
      kind: "failed",
      attempts: 4,
    });
    // The server refused to call a private address: nothing was attempted.
    expect(webhookState({ webhook_delivered: false, webhook_attempts: 0 }).kind).toBe("not_sent");
    // The QA case: three failures, the last retry still to come.
    expect(webhookState({ webhook_delivered: undefined, webhook_attempts: 3 })).toEqual({
      kind: "retrying",
      attempts: 3,
    });
    expect(webhookState({ webhook_delivered: undefined, webhook_attempts: 0 }).kind).toBe("none");
  });
});

describe("canRerun", () => {
  it("offers no rerun for a refused input", () => {
    expect(canRerun({ status: "validation_failed" })).toBe(false);
    expect(canRerun({ status: "failed" })).toBe(true);
    expect(canRerun({ status: "completed" })).toBe(true);
  });
});

describe("RunHistoryTable", () => {
  // CONTRACT-TEST: no Rerun for a refused run; a failing webhook says it failed
  it("offers no rerun on a refused run and says a webhook is failing", async () => {
    list.mockResolvedValue({
      items: [
        run({
          id: "trun_refused",
          status: "validation_failed",
          error_message: "Unknown override fields: foo",
          webhook_attempts: 1,
          webhook_delivered: undefined,
        }),
        run({ id: "trun_failing", status: "failed", webhook_attempts: 3 }),
        run({ id: "trun_done", status: "completed", webhook_delivered: true, webhook_attempts: 1 }),
      ],
      total: 3,
      page: 1,
      page_size: 20,
    });

    render(<RunHistoryTable triggerId="trg_1" />);

    const refusedRow = (await screen.findByTitle("trun_refused")).closest("tr")!;
    const failingRow = screen.getByTitle("trun_failing").closest("tr")!;
    const doneRow = screen.getByTitle("trun_done").closest("tr")!;

    const rerun = "triggers.runHistory.rerunTitle";
    expect(within(refusedRow).queryByRole("button", { name: rerun })).toBeNull();
    expect(within(failingRow).getByRole("button", { name: rerun })).toBeInTheDocument();
    expect(within(doneRow).getByRole("button", { name: rerun })).toBeInTheDocument();

    // Not "—": the column says the delivery is failing.
    expect(within(failingRow).getByTestId("run-webhook-status")).toHaveTextContent(
      "triggers.runHistory.webhookRetrying",
    );
    expect(within(doneRow).getByText("triggers.runHistory.webhookDeliveredLabel")).toBeInTheDocument();
  });
});
