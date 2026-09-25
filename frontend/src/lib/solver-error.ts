import type { ErrorTranslator } from "@/lib/errors";

/**
 * The part of a solver result that names a known refusal.
 *
 * `error_code` is set by the backend for refusals it can name, such as a
 * linear-only solver refusing a quadratic model. `error_message` beside it is
 * the same refusal in English.
 */
export interface CodedSolverError {
  error_code?: string | null;
  error_params?: Record<string, string> | null;
}

/**
 * A solver's error in the reader's language, or the English text it came with.
 *
 * The refusal of a quadratic model by JAOS, HiGHS, CBC or GLPK reached every
 * locale in English (QA, 2026-09-25). The result now carries a code; this reads
 * it from `errors.codes`. A code this build has no words for, and an error with
 * no code at all, show the English message unchanged.
 *
 * @param source    The result, or the stored `result_data` of an execution.
 * @param fallback  The English `error_message`.
 * @param t         `useTranslations("errors.codes")`.
 */
export function solverErrorText(
  source: CodedSolverError | null | undefined,
  fallback: string,
  t: ErrorTranslator,
): string {
  const code = source?.error_code;
  if (code && t.has(code)) {
    return t(code, source?.error_params ?? {});
  }
  return fallback;
}
