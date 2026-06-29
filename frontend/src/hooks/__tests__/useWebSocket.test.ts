import { describe, it, expect } from "vitest";
import { buildExecutionWsUrl } from "@/hooks/useWebSocket";

// Pure-helper tests only — the WS *component* render path (ExecutionProgress)
// has a known infinite-render issue and is skipped elsewhere. This covers the
// auth-token wiring that enables Live Solve streaming.
describe("buildExecutionWsUrl", () => {
  const opts = { protocol: "ws:", host: "localhost:3000" };

  it("appends the session token as a query param when present", () => {
    expect(buildExecutionWsUrl("exe_1", "tok_abc", opts)).toBe(
      "ws://localhost:3000/api/v2/ws/executions/exe_1?token=tok_abc"
    );
  });

  it("url-encodes the token", () => {
    expect(buildExecutionWsUrl("exe_1", "a/b+c=", opts)).toContain(
      "token=a%2Fb%2Bc%3D"
    );
  });

  it("builds the URL WITHOUT a token param for a cookie/email session (server auths from the JWT cookie)", () => {
    // No API key in localStorage (email/password login) must still open the
    // socket — the cookie is sent on the same-origin handshake.
    expect(buildExecutionWsUrl("exe_1", null, opts)).toBe(
      "ws://localhost:3000/api/v2/ws/executions/exe_1"
    );
    expect(buildExecutionWsUrl("exe_1", "", opts)).toBe(
      "ws://localhost:3000/api/v2/ws/executions/exe_1"
    );
  });

  it("returns null when there is no executionId", () => {
    expect(buildExecutionWsUrl(null, "tok", opts)).toBeNull();
  });

  it("uses wss for an https origin", () => {
    const url = buildExecutionWsUrl("exe_1", "tok", { protocol: "wss:", host: "jaot.io" });
    expect(url?.startsWith("wss://jaot.io/api/v2/ws/executions/exe_1?token=tok")).toBe(true);
  });
});
