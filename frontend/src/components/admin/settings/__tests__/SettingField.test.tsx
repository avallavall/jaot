/**
 * Every admin setting control is named by its setting's label.
 *
 * The switches on /admin/settings had role=switch and no name, so a screen
 * reader said "switch, off" with no word about what it turns off (browser QA,
 * 2026-09-24). The label sat beside the control with nothing linking the two.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { RegistryEntry } from "@/lib/api";
import { SettingField } from "../SettingField";

function entry(overrides: Partial<RegistryEntry>): RegistryEntry {
  return {
    key: "PUBLIC_REGISTRATION_ENABLED",
    label: "Public registration",
    description: "Let anybody create an account.",
    category: "access",
    setting_type: "bool",
    min_value: null,
    max_value: null,
    unit: null,
    is_secret: false,
    is_readonly: false,
    ...overrides,
  };
}

function renderField(e: RegistryEntry, value: string) {
  return render(
    <SettingField
      entry={e}
      value={value}
      envDefault={null}
      isModified={false}
      lastChangedBy={null}
      lastChangedAt={null}
      onChange={vi.fn()}
      onReset={vi.fn()}
    />,
  );
}

describe("an admin setting's control", () => {
  it("names a switch after its setting", () => {
    renderField(entry({}), "true");
    expect(screen.getByRole("switch", { name: "Public registration" })).toBeChecked();
  });

  it("names a switch after its setting when the setting was changed", () => {
    render(
      <SettingField
        entry={entry({})}
        value="false"
        envDefault={null}
        isModified
        lastChangedBy={null}
        lastChangedAt={null}
        onChange={vi.fn()}
        onReset={vi.fn()}
      />,
    );
    expect(screen.getByRole("switch", { name: "Public registration" })).not.toBeChecked();
  });

  it("names a number field after its setting", () => {
    renderField(
      entry({ key: "MAX_SOLVE_SECONDS", label: "Longest solve", setting_type: "int" }),
      "60",
    );
    expect(screen.getByRole("spinbutton", { name: "Longest solve" })).toHaveValue(60);
  });

  it("names a text field after its setting", () => {
    renderField(entry({ key: "APP_NAME", label: "Site name", setting_type: "str" }), "JAOT");
    expect(screen.getByRole("textbox", { name: "Site name" })).toHaveValue("JAOT");
  });
});
