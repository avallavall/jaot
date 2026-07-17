import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/builder/import-model", () => ({ parseModelFile: vi.fn() }));
vi.mock("@/lib/api", () => ({
  api: { createProject: vi.fn(), updateProjectDraft: vi.fn() },
}));

import { importFileToProject } from "../import-launch";
import { parseModelFile } from "@/lib/builder/import-model";
import { api } from "@/lib/api";

const PROBLEM = {
  variables: [{ name: "x", type: "continuous" as const, lower_bound: 0, upper_bound: 10 }],
  objective: { sense: "minimize" as const, expression: "x" },
  constraints: [],
};

describe("importFileToProject", () => {
  beforeEach(() => vi.clearAllMocks());

  it("parses, creates a project named from the file, seeds model_json, returns the id", async () => {
    vi.mocked(parseModelFile).mockResolvedValue({ problem: PROBLEM, baseName: "crew" });
    vi.mocked(api.createProject).mockResolvedValue({ id: "mp_1", draft_lock_version: 0 } as never);
    vi.mocked(api.updateProjectDraft).mockResolvedValue({} as never);

    const id = await importFileToProject(new File(["..."], "crew.mps"), "ws_1");

    expect(id).toBe("mp_1");
    expect(api.createProject).toHaveBeenCalledWith({ name: "crew", workspace_id: "ws_1" }, "ws_1");
    // Seeds ONLY model_json (no giant canvas) with the create response's lock version.
    expect(api.updateProjectDraft).toHaveBeenCalledWith("mp_1", { model_json: PROBLEM }, 0, "ws_1");
  });

  it("falls back to 'Imported model' when the file has no base name", async () => {
    vi.mocked(parseModelFile).mockResolvedValue({ problem: PROBLEM, baseName: "" });
    vi.mocked(api.createProject).mockResolvedValue({ id: "mp_2", draft_lock_version: 3 } as never);
    vi.mocked(api.updateProjectDraft).mockResolvedValue({} as never);

    await importFileToProject(new File([""], "x"));

    expect(api.createProject).toHaveBeenCalledWith(
      { name: "Imported model", workspace_id: undefined },
      undefined
    );
  });

  it("propagates a parse error without creating anything (caller shows the toast)", async () => {
    vi.mocked(parseModelFile).mockRejectedValue(new Error("bad file"));
    await expect(importFileToProject(new File([""], "x"))).rejects.toThrow("bad file");
    expect(api.createProject).not.toHaveBeenCalled();
  });
});
