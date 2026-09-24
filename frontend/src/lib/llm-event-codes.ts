// Backend emits stable enum codes in SSE status/error events (see app/services/llm/errors.py).
// Frontend translates them via next-intl so messages stay localized and never leak raw strings,
// stack traces, or token counts from the Anthropic upstream. Unknown codes fall back to generic
// internal_error / generating messages — failure-safe default during backend rollouts.

/** Status codes emitted during streaming. */
export type LLMStatusCode =
  | "generating"
  | "generating_variables"
  | "generating_constraints"
  | "assembling"
  | "explaining";

/** Error codes emitted on stream failure. Includes public + internal. */
export type LLMErrorCode =
  | "validation_failed"
  | "content_moderation"
  | "parametric_unsupported"
  | "assistant_paused"
  | "model_too_large"
  | "service_unavailable"
  | "internal_error";

/** next-intl keys relative to the `builder` namespace. */
export const STATUS_I18N_KEY: Record<LLMStatusCode, string> = {
  generating: "llm.status.generating",
  generating_variables: "llm.status.generatingVariables",
  generating_constraints: "llm.status.generatingConstraints",
  assembling: "llm.status.assembling",
  explaining: "llm.status.explaining",
};

/** next-intl keys relative to the `builder` namespace. */
export const ERROR_I18N_KEY: Record<LLMErrorCode, string> = {
  validation_failed: "llm.error.validationFailed",
  content_moderation: "llm.error.contentModeration",
  parametric_unsupported: "llm.error.parametricUnsupported",
  assistant_paused: "llm.error.assistantPaused",
  model_too_large: "llm.error.modelTooLarge",
  service_unavailable: "llm.error.serviceUnavailable",
  internal_error: "llm.error.internalError",
};

export function isLLMStatusCode(value: unknown): value is LLMStatusCode {
  return typeof value === "string" && Object.hasOwn(STATUS_I18N_KEY, value);
}

export function isLLMErrorCode(value: unknown): value is LLMErrorCode {
  return typeof value === "string" && Object.hasOwn(ERROR_I18N_KEY, value);
}

/** Unknown codes fall back to "generating" so the UI never shows a raw backend identifier. */
export function resolveStatusKey(code: string | undefined | null): string {
  if (isLLMStatusCode(code)) {
    return STATUS_I18N_KEY[code];
  }
  return STATUS_I18N_KEY.generating;
}

/** Unknown codes fall back to "internal_error" — keeps upstream detail out of the chat UI. */
export function resolveErrorKey(code: string | undefined | null): string {
  if (isLLMErrorCode(code)) {
    return ERROR_I18N_KEY[code];
  }
  return ERROR_I18N_KEY.internal_error;
}

/**
 * The code for a request the server refused before any stream started.
 *
 * Those refusals carry no SSE event, only a status and a body. Every one that
 * was not a 429 or a 5xx became "internal_error", "Something went wrong on our
 * side": the paused assistant (403, monthly budget spent) and a message the
 * moderation filter refused (422 with a sentence) both read as our fault, and
 * the moderation text in all five languages was never shown. The body is read
 * for its reason only; its wording never reaches the page.
 */
export async function preStreamErrorCode(response: Response): Promise<LLMErrorCode> {
  if (response.status === 429 || response.status >= 500) return "service_unavailable";
  let detail: unknown;
  try {
    detail = ((await response.clone().json()) as { detail?: unknown })?.detail;
  } catch {
    detail = undefined;
  }
  if (response.status === 403 && detail && typeof detail === "object") {
    const d = detail as { reason?: unknown; error?: unknown };
    if (d.reason === "llm_monthly_budget_exhausted" || d.error === "feature_not_available") {
      return "assistant_paused";
    }
  }
  if (response.status === 413 && detail && typeof detail === "object") {
    if ((detail as { error?: unknown }).error === "model_too_large") return "model_too_large";
  }
  // The moderation refusal is a sentence; a schema error is a list of fields.
  if (response.status === 422 && typeof detail === "string") return "content_moderation";
  return "internal_error";
}
