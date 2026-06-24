// Backend emits stable enum codes in SSE status/error events (see app/services/llm/errors.py).
// Frontend translates them via next-intl so messages stay localized and never leak raw strings,
// stack traces, or token counts from the Anthropic upstream. Unknown codes fall back to generic
// internal_error / generating messages — failure-safe default during backend rollouts.

/** Status codes emitted during streaming. */
export type LLMStatusCode =
  | "generating"
  | "generating_variables"
  | "generating_constraints"
  | "assembling";

/** Error codes emitted on stream failure. Includes public + internal. */
export type LLMErrorCode =
  | "validation_failed"
  | "content_moderation"
  | "insufficient_credits"
  | "parametric_unsupported"
  | "service_unavailable"
  | "internal_error";

/** next-intl keys relative to the `builder` namespace. */
export const STATUS_I18N_KEY: Record<LLMStatusCode, string> = {
  generating: "llm.status.generating",
  generating_variables: "llm.status.generatingVariables",
  generating_constraints: "llm.status.generatingConstraints",
  assembling: "llm.status.assembling",
};

/** next-intl keys relative to the `builder` namespace. */
export const ERROR_I18N_KEY: Record<LLMErrorCode, string> = {
  validation_failed: "llm.error.validationFailed",
  content_moderation: "llm.error.contentModeration",
  insufficient_credits: "llm.error.insufficientCredits",
  parametric_unsupported: "llm.error.parametricUnsupported",
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
