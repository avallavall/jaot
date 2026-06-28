/**
 * ExportModelButton — covers the async problem provider added so template/model
 * surfaces can render the problem (via a preview call) before exporting.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";

vi.unmock("next-intl");

const { mockExportModel, mockDownload, mockToastError } = vi.hoisted(() => ({
  mockExportModel: vi.fn(),
  mockDownload: vi.fn(),
  mockToastError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { fileExport: { exportModel: mockExportModel } } }));
vi.mock("@/lib/download", () => ({ downloadBlobAsFile: mockDownload }));
vi.mock("sonner", () => ({ toast: { error: mockToastError, success: vi.fn() } }));

import { ExportModelButton } from "../ExportModelButton";
import enMessages from "../../../../messages/en.json";

// radix DropdownMenu relies on pointer-capture / scrollIntoView, absent in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
  Element.prototype.setPointerCapture = Element.prototype.setPointerCapture ?? (() => {});
  Element.prototype.releasePointerCapture =
    Element.prototype.releasePointerCapture ?? (() => {});
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
});

function renderBtn(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={enMessages as Record<string, unknown>}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("ExportModelButton", () => {
  beforeEach(() => vi.clearAllMocks());

  it("awaits an async getProblem, then exports and downloads the chosen format", async () => {
    const problem = { name: "p", variables: [], objective: {} };
    const getProblem = vi.fn().mockResolvedValue(problem);
    mockExportModel.mockResolvedValue(new Blob(["data"]));
    const user = userEvent.setup();

    renderBtn(<ExportModelButton getProblem={getProblem} filenameBase="mymodel" />);
    await user.click(screen.getByRole("button", { name: /download model/i }));
    await user.click(await screen.findByRole("menuitem", { name: /mps format/i }));

    await waitFor(() => expect(mockExportModel).toHaveBeenCalledWith(problem, "mps"));
    expect(getProblem).toHaveBeenCalled();
    expect(mockDownload).toHaveBeenCalledWith(expect.any(Blob), "mymodel.mps");
  });

  it("surfaces an error and skips export when getProblem yields null", async () => {
    const user = userEvent.setup();
    renderBtn(<ExportModelButton getProblem={() => null} />);

    await user.click(screen.getByRole("button", { name: /download model/i }));
    await user.click(await screen.findByRole("menuitem", { name: /lp format/i }));

    await waitFor(() => expect(mockToastError).toHaveBeenCalled());
    expect(mockExportModel).not.toHaveBeenCalled();
  });
});
