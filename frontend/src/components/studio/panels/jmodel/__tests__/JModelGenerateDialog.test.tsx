import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { JModelGenerateDialog } from "../JModelGenerateDialog";
import type { DslGenerateResult } from "@/lib/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

// The class must be defined INSIDE the factory (vi.mock is hoisted above imports).
vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }
  return { api: { generateDsl: vi.fn() }, ApiError };
});

import { api, ApiError } from "@/lib/api";
import { toast } from "sonner";

const generateDsl = api.generateDsl as unknown as ReturnType<typeof vi.fn>;

const GOOD_SOURCE = "var x >= 0;\nminimize obj: x;";

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof JModelGenerateDialog>> = {},
) {
  const onGenerated = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <JModelGenerateDialog
      open
      onOpenChange={onOpenChange}
      currentSource=""
      onGenerated={onGenerated}
      {...overrides}
    />,
  );
  return { onGenerated, onOpenChange };
}

describe("JModelGenerateDialog", () => {
  beforeEach(() => {
    generateDsl.mockReset();
    vi.clearAllMocks();
  });

  it("disables submit until there is a description or attachment", () => {
    renderDialog();
    expect(screen.getByTestId("studio-jmodel-generate-submit")).toBeDisabled();
    fireEvent.change(screen.getByTestId("studio-jmodel-generate-description"), {
      target: { value: "assign workers to tasks" },
    });
    expect(
      screen.getByTestId("studio-jmodel-generate-submit"),
    ).not.toBeDisabled();
  });

  it("generates, hands the source to the editor, and closes on success", async () => {
    const result: DslGenerateResult = {
      ok: true,
      source: GOOD_SOURCE,
      attempts: 1,
    };
    generateDsl.mockResolvedValue(result);
    const { onGenerated, onOpenChange } = renderDialog();

    fireEvent.change(screen.getByTestId("studio-jmodel-generate-description"), {
      target: { value: "minimize x" },
    });
    fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

    await waitFor(() => expect(onGenerated).toHaveBeenCalledWith(GOOD_SOURCE));
    expect(generateDsl).toHaveBeenCalledWith({
      description: "minimize x",
      attachments: [],
      currentSource: null,
      // The advanced-model choice rides along on every call; off unless asked for.
      useAdvancedModel: false,
    });
    expect(toast.success).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("still loads a best-effort draft that did not compile, warning the user", async () => {
    const result: DslGenerateResult = {
      ok: false,
      source: "var x binary\nmaximize o: x;",
      error: { message: "expected ';'", position: 12 },
      attempts: 3,
    };
    generateDsl.mockResolvedValue(result);
    const { onGenerated } = renderDialog();

    fireEvent.change(screen.getByTestId("studio-jmodel-generate-description"), {
      target: { value: "a model" },
    });
    fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

    await waitFor(() =>
      expect(onGenerated).toHaveBeenCalledWith(result.source),
    );
    expect(toast.warning).toHaveBeenCalled();
  });

  it("shows an error and does not apply when nothing was generated", async () => {
    generateDsl.mockResolvedValue({ ok: false, source: null, attempts: 3 });
    const { onGenerated } = renderDialog();

    fireEvent.change(screen.getByTestId("studio-jmodel-generate-description"), {
      target: { value: "gibberish" },
    });
    fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

    await waitFor(() =>
      expect(
        screen.getByTestId("studio-jmodel-generate-error"),
      ).toBeInTheDocument(),
    );
    expect(onGenerated).not.toHaveBeenCalled();
  });

  it("surfaces an API error (e.g. budget exhausted) inline", async () => {
    generateDsl.mockRejectedValue(
      new ApiError(403, "monthly AI budget reached"),
    );
    const { onGenerated } = renderDialog();

    fireEvent.change(screen.getByTestId("studio-jmodel-generate-description"), {
      target: { value: "a knapsack" },
    });
    fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

    // The i18n mock echoes the key (it can't interpolate the real translation), so we
    // assert the error surface appears and nothing was applied — the ApiError message is
    // threaded through {message} at runtime.
    await waitFor(() =>
      expect(
        screen.getByTestId("studio-jmodel-generate-error"),
      ).toBeInTheDocument(),
    );
    expect(onGenerated).not.toHaveBeenCalled();
  });

  it("passes the current editor source for refinement", async () => {
    generateDsl.mockResolvedValue({
      ok: true,
      source: GOOD_SOURCE,
      attempts: 1,
    });
    renderDialog({ currentSource: "var y >= 0;" });

    fireEvent.change(screen.getByTestId("studio-jmodel-generate-description"), {
      target: { value: "add a bound" },
    });
    fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

    await waitFor(() =>
      expect(generateDsl).toHaveBeenCalledWith(
        expect.objectContaining({ currentSource: "var y >= 0;" }),
      ),
    );
  });

  it("caps a multi-file pick at the limit AND says so", async () => {
    // Picking 5 files at once must keep 4 and surface the "too many" error —
    // the stale-closure version silently dropped the extras with no message.
    renderDialog();
    const files = Array.from(
      { length: 5 },
      (_, i) => new File([`img${i}`], `f${i}.png`, { type: "image/png" }),
    );
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files } });

    await waitFor(() =>
      expect(
        screen.getByTestId("studio-jmodel-generate-error"),
      ).toBeInTheDocument(),
    );
    // 4 attachments listed, the 5th dropped.
    expect(screen.getAllByText(/^f\d\.png$/)).toHaveLength(4);
  });
  // The owner asked for the advanced-model choice on EVERY LLM surface. This dialog was
  // the one left out when the toggle landed (it shipped to the two chats and the three
  // explainers), and /dsl/generate had the model pinned to the default server-side too.
  describe("advanced model choice", () => {
    it("offers the toggle", () => {
      renderDialog();
      expect(screen.getByTestId("advanced-model-toggle")).toBeInTheDocument();
    });

    it("defaults to the standard model", async () => {
      generateDsl.mockResolvedValue({
        ok: true,
        source: GOOD_SOURCE,
      } as DslGenerateResult);
      renderDialog();
      fireEvent.change(
        screen.getByTestId("studio-jmodel-generate-description"),
        {
          target: { value: "assign workers to tasks" },
        },
      );
      fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

      await waitFor(() => expect(generateDsl).toHaveBeenCalled());
      expect(generateDsl.mock.calls[0][0]).toMatchObject({
        useAdvancedModel: false,
      });
    });

    it("sends the choice when the toggle is on", async () => {
      generateDsl.mockResolvedValue({
        ok: true,
        source: GOOD_SOURCE,
      } as DslGenerateResult);
      renderDialog();
      fireEvent.click(screen.getByTestId("advanced-model-toggle"));
      fireEvent.change(
        screen.getByTestId("studio-jmodel-generate-description"),
        {
          target: { value: "assign workers to tasks" },
        },
      );
      fireEvent.click(screen.getByTestId("studio-jmodel-generate-submit"));

      await waitFor(() => expect(generateDsl).toHaveBeenCalled());
      // The flag has to reach the request — a toggle that only paints is worse than none.
      expect(generateDsl.mock.calls[0][0]).toMatchObject({
        useAdvancedModel: true,
      });
    });
  });
});
