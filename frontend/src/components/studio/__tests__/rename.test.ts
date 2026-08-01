import { describe, it, expect, vi } from "vitest";
import { commitRename, resolveRenameBlur } from "../rename";

describe("resolveRenameBlur", () => {
  // CONTRACT-TEST: Escape discards a rename — it must never reach the server.
  it("discards the edit and restores the stored name when Escape cancelled it", () => {
    expect(
      resolveRenameBlur({ draft: "Typed but cancelled", storedName: "Crew Scheduler", cancelled: true })
    ).toEqual({ action: "discard", draft: "Crew Scheduler" });
  });

  it("restores the stored name when the field was left blank", () => {
    expect(resolveRenameBlur({ draft: "   ", storedName: "Crew Scheduler", cancelled: false })).toEqual({
      action: "discard",
      draft: "Crew Scheduler",
    });
  });

  it("commits the trimmed draft otherwise", () => {
    expect(
      resolveRenameBlur({ draft: "  Fleet Router  ", storedName: "Crew Scheduler", cancelled: false })
    ).toEqual({ action: "commit", draft: "Fleet Router" });
  });
});

describe("commitRename", () => {
  it("optimistically renames the store and persists via update", async () => {
    const setName = vi.fn();
    const onError = vi.fn();
    const update = vi.fn().mockResolvedValue({});
    await commitRename({
      modelId: "mp_1",
      next: "  Crew Scheduler  ",
      current: "Untitled Model",
      setName,
      update,
      onError,
    });
    expect(setName).toHaveBeenCalledWith("Crew Scheduler");
    expect(update).toHaveBeenCalledWith("mp_1", { name: "Crew Scheduler" });
    expect(onError).not.toHaveBeenCalled();
  });

  it("reverts the store name and reports on persist failure", async () => {
    const setName = vi.fn();
    const onError = vi.fn();
    const update = vi.fn().mockRejectedValue(new Error("boom"));
    await commitRename({
      modelId: "mp_1",
      next: "New name",
      current: "Old name",
      setName,
      update,
      onError,
    });
    expect(setName).toHaveBeenNthCalledWith(1, "New name"); // optimistic
    expect(setName).toHaveBeenNthCalledWith(2, "Old name"); // revert
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("does not revert when another writer renamed meanwhile (getName mismatch)", async () => {
    const setName = vi.fn();
    const onError = vi.fn();
    const update = vi.fn().mockRejectedValue(new Error("boom"));
    await commitRename({
      modelId: "mp_1",
      next: "New name",
      current: "Old name",
      setName,
      update,
      onError,
      // the assistant auto-rename landed while our PATCH was in flight
      getName: () => "Assistant name",
    });
    expect(setName).toHaveBeenCalledTimes(1); // optimistic only — no revert
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("no-ops on blank, unchanged, or unsaved (new) projects", async () => {
    const setName = vi.fn();
    const onError = vi.fn();
    const update = vi.fn().mockResolvedValue({});
    await commitRename({ modelId: "mp_1", next: "   ", current: "Old", setName, update, onError });
    await commitRename({ modelId: "mp_1", next: "Old", current: "Old", setName, update, onError });
    await commitRename({ modelId: "new", next: "X", current: "Old", setName, update, onError });
    expect(setName).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
  });
});
