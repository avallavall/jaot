/**
 * The member table, seen by the organization owner (QA, 2026-09-25).
 *
 * The owner's own row carried a role select and a remove button the server
 * always refuses. Role names were the raw English values in every locale, the
 * role-change toast printed the raw value, and the remove button was an icon
 * with no accessible name.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { WorkspaceMember } from "@/lib/types";
import { ApiError } from "@/lib/api";

const updateMemberRole = vi.fn();
const removeMember = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      updateMemberRole: (...a: unknown[]) => updateMemberRole(...a),
      removeMember: (...a: unknown[]) => removeMember(...a),
    },
  };
});

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "usr_owner" }, workspaceRole: "admin" }),
}));

vi.mock("@/hooks/usePermission", () => ({ usePermission: () => true }));

// The shared mock drops the values of a key with no placeholder in its name.
// This one keeps them, so a test can see WHICH role a message names.
vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => {
    const t = (key: string, values?: Record<string, unknown>) =>
      values && Object.keys(values).length > 0
        ? `${ns}.${key} ${JSON.stringify(values)}`
        : `${ns}.${key}`;
    t.has = () => true;
    return t;
  },
  useLocale: () => "en",
}));

const { toast, confirmCallback } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn() },
  confirmCallback: vi.fn(),
}));
vi.mock("sonner", () => ({ toast }));
vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({ confirmCallback, DialogComponent: () => null }),
}));

import { MemberTable } from "../MemberTable";

const owner: WorkspaceMember = {
  id: "wkm_1",
  user_id: "usr_owner",
  user_name: "Olive Owner",
  user_email: "olive@example.com",
  role: "admin",
  joined_at: "2026-09-25T10:00:00Z",
  invited_by: null,
  is_org_owner: true,
};
const member: WorkspaceMember = {
  id: "wkm_2",
  user_id: "usr_max",
  user_name: "Max Member",
  user_email: "max@example.com",
  role: "editor",
  joined_at: "2026-09-25T10:00:00Z",
  invited_by: "usr_owner",
  is_org_owner: false,
};

function renderTable(members = [owner, member]) {
  return render(
    <MemberTable workspaceId="wks_1" members={members} onMembersChange={vi.fn()} />,
  );
}

function row(name: string) {
  return screen.getByText(name).closest("tr") as HTMLElement;
}

describe("MemberTable", () => {
  // The Radix select relies on pointer capture and scrollIntoView, absent in jsdom.
  beforeAll(() => {
    Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
    Element.prototype.setPointerCapture = Element.prototype.setPointerCapture ?? (() => {});
    Element.prototype.releasePointerCapture =
      Element.prototype.releasePointerCapture ?? (() => {});
    Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
  });

  beforeEach(() => {
    updateMemberRole.mockReset().mockResolvedValue(undefined);
    removeMember.mockReset();
    toast.success.mockReset();
    toast.error.mockReset();
    confirmCallback.mockReset();
  });

  // CONTRACT-TEST: the owner's own row offers no control the server refuses.
  it("offers no role select and no remove button on your own row", () => {
    renderTable();

    const own = row("Olive Owner");
    expect(within(own).queryByRole("combobox")).toBeNull();
    expect(within(own).queryByRole("button")).toBeNull();
    // The role still shows, in the reader's language.
    expect(within(own).getByText("workspace.invite.roles.admin")).toBeInTheDocument();
  });

  it("offers no control on the organization owner's row to another admin", () => {
    renderTable([{ ...owner, user_id: "usr_someone_else" }, member]);

    const ownerRow = row("Olive Owner");
    expect(within(ownerRow).queryByRole("combobox")).toBeNull();
    expect(within(ownerRow).queryByRole("button")).toBeNull();
  });

  it("names the other member's controls, in the reader's language", () => {
    renderTable();

    const other = row("Max Member");
    expect(
      within(other).getByRole("combobox", { name: /workspace\.memberTable\.roleOf/ }),
    ).toHaveTextContent("workspace.invite.roles.editor");
    expect(
      within(other).getByRole("button", { name: /workspace\.memberTable\.removeMemberNamed/ }),
    ).toBeInTheDocument();
  });

  it("names the new role in the toast, not the raw value", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(within(row("Max Member")).getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "workspace.invite.roles.viewer" }));

    expect(updateMemberRole).toHaveBeenCalledWith("wks_1", "usr_max", "viewer");
    expect(toast.success).toHaveBeenCalledWith(
      `workspace.memberTable.roleUpdated ${JSON.stringify({
        name: "Max Member",
        role: "workspace.invite.roles.viewer",
      })}`,
    );
  });

  it("shows a refusal in the reader's language", async () => {
    const user = userEvent.setup();
    removeMember.mockRejectedValue(
      new ApiError(400, "Cannot remove the organization owner", undefined, "workspace.owner_not_removable"),
    );
    renderTable();

    await user.click(
      within(row("Max Member")).getByRole("button", {
        name: /workspace\.memberTable\.removeMemberNamed/,
      }),
    );
    const [, onConfirm] = confirmCallback.mock.calls[0];
    await onConfirm();

    expect(toast.error).toHaveBeenCalledWith("errors.codes.workspace.owner_not_removable");
  });
});
