import { describe, expect, it } from "vitest";
import { preStreamErrorCode } from "@/lib/llm-event-codes";

function refusal(status: number, detail?: unknown): Response {
  return new Response(detail === undefined ? "" : JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("preStreamErrorCode", () => {
  // Every refusal that was not a 429 or a 5xx used to read "Something went wrong
  // on our side", including the two that are not our fault and not transient.
  it("names a paused assistant (monthly budget spent)", async () => {
    const response = refusal(403, {
      error: "feature_not_available",
      reason: "llm_monthly_budget_exhausted",
      message: "The AI assistant is taking a short break",
    });
    expect(await preStreamErrorCode(response)).toBe("assistant_paused");
  });

  it("names a model too large for the assistant to work on", async () => {
    const response = refusal(413, { error: "model_too_large", message: "too large" });
    expect(await preStreamErrorCode(response)).toBe("model_too_large");
  });

  it("names a message the moderation filter refused", async () => {
    expect(await preStreamErrorCode(refusal(422, "Message not allowed"))).toBe(
      "content_moderation",
    );
  });

  it("does not call a schema error a moderation refusal", async () => {
    const schemaError = [{ loc: ["body", "message"], msg: "too long" }];
    expect(await preStreamErrorCode(refusal(422, schemaError))).toBe("internal_error");
  });

  it("keeps rate limits and server errors as a temporary outage", async () => {
    expect(await preStreamErrorCode(refusal(429))).toBe("service_unavailable");
    expect(await preStreamErrorCode(refusal(503))).toBe("service_unavailable");
  });

  it("falls back for anything else, including a body that is not JSON", async () => {
    expect(await preStreamErrorCode(new Response("<html>", { status: 400 }))).toBe(
      "internal_error",
    );
  });
});
