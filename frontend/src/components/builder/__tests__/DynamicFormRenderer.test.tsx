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
import { NextIntlClientProvider } from "next-intl";
import { describe, it, expect, vi } from "vitest";
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
