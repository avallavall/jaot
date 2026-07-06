// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { api } from "../api";

// Helper to set up fetch mock
function mockFetch(body: unknown, status = 200) {
  return vi.spyOn(global, "fetch").mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

describe("ApiClient", () => {
  beforeEach(() => {
    localStorage.clear();
    api.clearApiKey();
  });

  describe("request - auth header", () => {
    it("sends Authorization: Bearer header when API key is set", async () => {
      const spy = mockFetch({ success: true });
      api.setApiKey("ok_test_key");

      await api.request("/api/v2/auth/me");

      expect(spy).toHaveBeenCalledWith(
        expect.stringContaining("/api/v2/auth/me"),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: "Bearer ok_test_key",
          }),
        })
      );
    });

    it("does not send Authorization header when no API key", async () => {
      const spy = mockFetch({ items: [] });

      await api.request("/api/v2/models/catalog");

      const callHeaders = (spy.mock.calls[0][1] as RequestInit)?.headers as Record<string, string>;
      expect(callHeaders?.Authorization).toBeUndefined();
    });
  });

  describe("request - error handling", () => {
    it("throws ApiError with backend detail message on non-200", async () => {
      mockFetch({ detail: "API key not found" }, 401);

      await expect(api.request("/api/v2/auth/me")).rejects.toThrow("API key not found");
    });

    it("throws generic HTTP error when backend returns no detail", async () => {
      mockFetch({}, 500);

      await expect(api.request("/api/v2/something", { retry: false })).rejects.toThrow("Request failed (500)");
    });
  });

  describe("setApiKey / clearApiKey / isAuthenticated", () => {
    it("stores key in localStorage", () => {
      api.setApiKey("ok_live_abc");
      expect(localStorage.getItem("jaot_api_key")).toBe("ok_live_abc");
    });

    it("isAuthenticated returns true when key is set", () => {
      api.setApiKey("ok_live_abc");
      expect(api.isAuthenticated()).toBe(true);
    });

    it("isAuthenticated returns false after clearApiKey", () => {
      api.setApiKey("ok_live_abc");
      api.clearApiKey();
      expect(api.isAuthenticated()).toBe(false);
    });

    it("reads key from localStorage on construction", () => {
      localStorage.setItem("jaot_api_key", "ok_persisted");
      expect(api.getApiKey()).toBe("ok_persisted");
    });
  });

  describe("login", () => {
    it("stores the API key and returns result on success", async () => {
      mockFetch({
        success: true,
        user: { id: "u1", name: "Test", email: "t@t.com", is_admin: false },
        organization: { id: "o1", name: "Org", plan: "free", credits_balance: 100 },
        permissions: { can_build_plugins: false, ai_builder_enabled: false },
      });

      const result = await api.login("ok_live_testkey");

      expect(result.success).toBe(true);
      expect(localStorage.getItem("jaot_api_key")).toBe("ok_live_testkey");
    });
  });

  describe("request - JSON body", () => {
    it("sends Content-Type: application/json when body is provided", async () => {
      const spy = mockFetch({ id: "exec1" }, 200);
      api.setApiKey("key");

      await api.request("/api/v2/models/m1/execute", {
        method: "POST",
        body: JSON.stringify({ input_data: {} }),
      });

      const callHeaders = (spy.mock.calls[0][1] as RequestInit)?.headers as Record<string, string>;
      expect(callHeaders["Content-Type"]).toBe("application/json");
    });
  });

  describe("solveMultiObjective - workspace_id", () => {
    it("sends workspace_id as query param when workspaceId is provided", async () => {
      const spy = mockFetch({ n_solved: 5, pareto_points: [] }, 200);
      localStorage.setItem("jaot_api_key", "ok_test_key");

      const problem = { name: "test", variables: [], objective: { sense: "minimize" as const, expression: "x" }, constraints: [] };
      const config = { mode: "epsilon" as const, objectives: [], n_points: 5 };

      await api.solveMultiObjective(problem, config, "ws_abc123");

      const url = spy.mock.calls[0][0] as string;
      expect(url).toContain("workspace_id=ws_abc123");
    });

    it("does not send workspace_id when workspaceId is omitted", async () => {
      const spy = mockFetch({ n_solved: 5, pareto_points: [] }, 200);
      localStorage.setItem("jaot_api_key", "ok_test_key");

      const problem = { name: "test", variables: [], objective: { sense: "minimize" as const, expression: "x" }, constraints: [] };
      const config = { mode: "epsilon" as const, objectives: [], n_points: 5 };

      await api.solveMultiObjective(problem, config);

      const url = spy.mock.calls[0][0] as string;
      expect(url).not.toContain("workspace_id");
    });
  });

  describe("solve - provenance", () => {
    const problem = {
      name: "test",
      variables: [],
      objective: { sense: "minimize" as const, expression: "x" },
      constraints: [],
    };

    it("sends origin/source_kind/source_id as query params", async () => {
      const spy = mockFetch({ status: "optimal" }, 200);
      localStorage.setItem("jaot_api_key", "ok_test_key");

      await api.solve(problem, undefined, {
        origin: "visual_builder",
        sourceKind: "builder_document",
        sourceId: "bld_123",
      });

      const url = spy.mock.calls[0][0] as string;
      expect(url).toContain("origin=visual_builder");
      expect(url).toContain("source_kind=builder_document");
      expect(url).toContain("source_id=bld_123");
    });

    it("omits source_id when null but still sends origin", async () => {
      const spy = mockFetch({ status: "optimal" }, 200);
      localStorage.setItem("jaot_api_key", "ok_test_key");

      await api.solve(problem, undefined, {
        origin: "ai_builder",
        sourceKind: "llm_conversation",
        sourceId: null,
      });

      const url = spy.mock.calls[0][0] as string;
      expect(url).toContain("origin=ai_builder");
      expect(url).not.toContain("source_id=");
    });

    it("sends no provenance params when source is omitted", async () => {
      const spy = mockFetch({ status: "optimal" }, 200);
      localStorage.setItem("jaot_api_key", "ok_test_key");

      await api.solve(problem);

      const url = spy.mock.calls[0][0] as string;
      expect(url).not.toContain("origin=");
      expect(url).not.toContain("source_kind=");
    });
  });

  describe("solve - 202 async degrade (ADR-007 S5)", () => {
    const problem = {
      name: "test",
      variables: [],
      objective: { sense: "minimize" as const, expression: "x" },
      constraints: [],
    };

    // A long solve degrades to 202 + envelope; the poll GET then returns terminal.
    function mock202ThenPoll(pollBody: unknown) {
      const envelope = {
        task_id: "task-abc",
        execution_id: "exe_deg",
        status: "pending",
        poll_url: "/api/v2/solve/async/task-abc",
      };
      return vi.spyOn(global, "fetch").mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        const body = url.includes("/solve/async/task-abc") ? pollBody : envelope;
        const status = url.includes("/solve/async/task-abc") ? 200 : 202;
        return Promise.resolve({ ok: true, status, json: async () => body } as Response);
      });
    }

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("polls a degraded solve to completion and injects execution_id", async () => {
      localStorage.setItem("jaot_api_key", "ok_test_key");
      mock202ThenPoll({
        task_id: "task-abc",
        status: "completed",
        solver_used: "scip",
        result: { status: "success", result: { status: "optimal", objective_value: 10, solution: {} } },
      });

      const result = await api.solve(problem);

      expect(result.status).toBe("optimal");
      expect(result.objective_value).toBe(10);
      // The worker's raw result dump omits execution_id; it's injected from the 202 envelope.
      expect(result.execution_id).toBe("exe_deg");
      expect(result.solver_used).toBe("scip");
    });

    it("throws when a degraded solve ends failed", async () => {
      localStorage.setItem("jaot_api_key", "ok_test_key");
      mock202ThenPoll({ task_id: "task-abc", status: "failed", error: "solver exploded" });

      await expect(api.solve(problem)).rejects.toThrow("solver exploded");
    });

    it("resolves a degraded multi-objective solve to its Pareto result", async () => {
      localStorage.setItem("jaot_api_key", "ok_test_key");
      mock202ThenPoll({
        task_id: "task-abc",
        status: "completed",
        result: {
          status: "success",
          multi_objective: true,
          result: { n_solved: 3, pareto_points: [1, 2, 3], mode: "epsilon", labels: [], total_credits_used: 3 },
        },
      });

      const config = { mode: "epsilon" as const, objectives: [], n_points: 3 };
      const result = await api.solveMultiObjective(problem, config);

      expect(result.n_solved).toBe(3);
      expect(result.pareto_points).toHaveLength(3);
    });
  });

  describe("fileExport.exportModel", () => {
    const problem = {
      name: "t",
      variables: [],
      objective: { sense: "maximize" as const, expression: "x" },
      constraints: [],
    };

    it("POSTs the problem to the model-export endpoint and returns a blob", async () => {
      const blob = new Blob(["MODEL"], { type: "application/x-mps" });
      const spy = vi.spyOn(global, "fetch").mockResolvedValueOnce({
        ok: true,
        status: 200,
        blob: async () => blob,
      } as unknown as Response);
      localStorage.setItem("jaot_api_key", "ok_test_key");

      const result = await api.fileExport.exportModel(problem, "mps");

      const [url, init] = spy.mock.calls[0];
      expect(url).toContain("/api/v2/solve/export/model/mps");
      expect((init as RequestInit).method).toBe("POST");
      expect(result).toBe(blob);
    });
  });
});
