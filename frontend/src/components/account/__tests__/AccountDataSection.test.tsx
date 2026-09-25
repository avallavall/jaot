/**
 * Deleting the account with a wrong password says so (QA, 2026-09-25).
 *
 * The API answered 401, the client took it for an expired session, refreshed
 * and sent the DELETE again, and the refusal went to a dialog this section never
 * rendered. The server now answers 403 with a code, and the page prints it.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const deleteUserAccount = vi.fn();
const exportUserData = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      deleteUserAccount: (...a: unknown[]) => deleteUserAccount(...a),
      exportUserData: (...a: unknown[]) => exportUserData(...a),
    },
  };
});

import { AccountDataSection } from "../AccountDataSection";

async function tryToDelete(password: string) {
  const user = userEvent.setup();
  render(<AccountDataSection />);
  await user.click(screen.getByRole("button", { name: /workspace\.accountData\.deleteButton/ }));
  await user.type(screen.getByPlaceholderText("workspace.accountData.deleteTypePlaceholder"), "DELETE");
  await user.type(screen.getByLabelText("workspace.accountData.deletePasswordPlaceholder"), password);
  await user.click(screen.getByRole("button", { name: "workspace.accountData.permanentlyDelete" }));
  return user;
}

describe("AccountDataSection", () => {
  beforeEach(() => {
    deleteUserAccount.mockReset();
    exportUserData.mockReset();
  });

  // CONTRACT-TEST: a wrong password on account deletion is shown on the page.
  it("shows why a wrong password was refused", async () => {
    deleteUserAccount.mockRejectedValue(
      new ApiError(403, "Invalid password", "Invalid password", "account.wrong_password"),
    );
    await tryToDelete("not-my-password");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "errors.codes.account.wrong_password",
    );
    expect(deleteUserAccount).toHaveBeenCalledTimes(1);
  });

  it("clears the message once the password is typed again", async () => {
    deleteUserAccount.mockRejectedValue(
      new ApiError(403, "Invalid password", "Invalid password", "account.wrong_password"),
    );
    const user = await tryToDelete("not-my-password");
    await screen.findByRole("alert");

    await user.type(screen.getByLabelText("workspace.accountData.deletePasswordPlaceholder"), "x");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the export's result", async () => {
    const user = userEvent.setup();
    exportUserData.mockResolvedValue(undefined);
    render(<AccountDataSection />);

    await user.click(screen.getByRole("button", { name: "workspace.accountData.exportButton" }));

    expect(await screen.findByText("workspace.accountData.exportSuccess")).toBeInTheDocument();
  });
});
