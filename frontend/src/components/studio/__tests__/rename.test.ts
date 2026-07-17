import { describe, it, expect, vi } from "vitest";
import { commitRename } from "../rename";

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
