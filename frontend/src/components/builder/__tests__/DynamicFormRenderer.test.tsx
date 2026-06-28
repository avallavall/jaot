/**
 * Regression test for the "empty template/model form" bug.
 *
 * A catalog model (e.g. mcat_… "demo-finance") with `input_fields: []` was
 * rendered as an empty card with only Load-Example / Clear-All / Solve buttons
 * and no content — looking broken to the user. DynamicFormRenderer must instead
 * show a clear "no input fields" message and NOT render the Solve form.
 *
 * Uses the real locale messages (bypassing the global next-intl mock) so the
 * assertion checks the actual translated copy.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, it, expect, vi, beforeAll } from "vitest";
import { DynamicFormRenderer } from "../DynamicFormRenderer";
import type { FieldSchema } from "../FormFieldRenderer";

vi.unmock("next-intl");

import enMessages from "../../../../messages/en.json";

type Messages = Record<string, unknown>;

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={enMessages as Messages}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("DynamicFormRenderer — empty input_fields", () => {
  it("shows an informational message and no Solve button when there are no fields", () => {
    renderWithIntl(
      <DynamicFormRenderer inputFields={[]} exampleInput={{}} onSubmit={vi.fn()} />
    );

    expect(
      screen.getByText("This model has no input fields to fill in.")
    ).toBeInTheDocument();
    // The non-functional form (Solve / Load Example) must NOT be rendered.
    expect(screen.queryByRole("button", { name: /solve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /load example/i })).not.toBeInTheDocument();
  });

  it("renders the form (with Solve) when input fields are present", () => {
    const fields: FieldSchema[] = [
      { name: "budget", type: "number", label: "Budget", required: true } as FieldSchema,
    ];

    renderWithIntl(
      <DynamicFormRenderer
        inputFields={fields}
        exampleInput={{ budget: 100 }}
        onSubmit={vi.fn()}
      />
    );

    expect(
      screen.queryByText("This model has no input fields to fill in.")
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /solve/i })).toBeInTheDocument();
  });
});

describe("DynamicFormRenderer — export model action", () => {
  const fields: FieldSchema[] = [
    { name: "budget", type: "number", label: "Budget", required: true } as FieldSchema,
  ];

  it("renders the export trigger when getExportProblem is provided", () => {
    renderWithIntl(
      <DynamicFormRenderer
        inputFields={fields}
        exampleInput={{ budget: 100 }}
        onSubmit={vi.fn()}
        getExportProblem={vi.fn().mockResolvedValue(null)}
      />
    );

    expect(
      screen.getByRole("button", { name: /download model/i })
    ).toBeInTheDocument();
  });

  it("omits the export trigger when getExportProblem is not provided", () => {
    renderWithIntl(
      <DynamicFormRenderer
        inputFields={fields}
        exampleInput={{ budget: 100 }}
        onSubmit={vi.fn()}
      />
    );

    expect(
      screen.queryByRole("button", { name: /download model/i })
    ).not.toBeInTheDocument();
  });
});

describe("DynamicFormRenderer — export validates before previewing", () => {
  // radix DropdownMenu relies on pointer-capture / scrollIntoView, absent in jsdom.
  beforeAll(() => {
    Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
    Element.prototype.setPointerCapture = Element.prototype.setPointerCapture ?? (() => {});
    Element.prototype.releasePointerCapture =
      Element.prototype.releasePointerCapture ?? (() => {});
    Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
  });

  it("blocks export and surfaces field errors when required input is missing", async () => {
    const getExportProblem = vi.fn();
    const fields: FieldSchema[] = [
      { name: "budget", type: "number", label: "Budget", required: true } as FieldSchema,
    ];
    const user = userEvent.setup();

    renderWithIntl(
      <DynamicFormRenderer
        inputFields={fields}
        exampleInput={{ budget: 100 }}
        onSubmit={vi.fn()}
        getExportProblem={getExportProblem}
        exportFilenameBase="cflp"
      />
    );

    // Form left empty → export must validate first and never hit the preview.
    await user.click(screen.getByRole("button", { name: /download model/i }));
    await user.click(await screen.findByRole("menuitem", { name: /mps format/i }));

    expect(await screen.findByText("Budget is required")).toBeInTheDocument();
    expect(getExportProblem).not.toHaveBeenCalled();
  });
});
